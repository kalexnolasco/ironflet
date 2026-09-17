"""The catalogue side of OpenRouter: which models exist, what they cost, what they can do.

Split out from `agent.py` on purpose. That module is the conversation — the tools,
the proposals, the rule that nothing it does can write to the training log. This
one is a list of models and their prices, it does no reasoning, and it is the
only part of the coach that can be exercised without an API key: `GET
/api/v1/models` is **public**, which is what makes a live dropdown possible on a
device that has not been set up yet.

## Prices are read, never written down

There was a hardcoded price table in `views/profile.py` and it was already a
liability: two copies of the same numbers, one in prose for a screen and one in
arithmetic for the cost line, drifting apart the first time OpenRouter changed a
rate. The catalogue returns `pricing` per model, in **dollars per token**, so
this module converts once and nothing in the app has an opinion about what a
model costs.

Only one number is persisted: the price of the model Alex actually picked, saved
next to the choice, so the "this answer cost ≈ $X" line still works in a gym with
no signal. It is a snapshot and is labelled as one.

## Only models that can call tools

417 models, 348 of which support tool calling. The other 69 would look fine in a
dropdown and then quietly break the coach: it cannot read a single thing about
Alex's training without tools, so on one of those it would either refuse or —
worse — answer from imagination. `supported_parameters` carries `"tools"`, and
anything without it never reaches the list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

BASE_URL = "https://openrouter.ai/api/v1"
MODELS_URL = f"{BASE_URL}/models"

#: Sent so the request is attributable on OpenRouter's side. Both are optional.
#:
#: The title header is `X-OpenRouter-Title`, NOT `X-Title`. The short name is the
#: widely-repeated one and is still accepted for backwards compatibility, but the
#: current documentation names the long one — checked against the raw docs
#: precisely because the short one is what everybody remembers.
APP_URL = "https://github.com/kalexnolasco/ironflet"
APP_TITLE = "IronFlet"

#: What the dropdown offers before Alex goes looking. Ids only — no prices, no
#: descriptions, nothing that goes stale — resolved against the live catalogue
#: so the numbers beside them are always today's. An id that OpenRouter has
#: retired simply drops out of the list instead of showing a price for something
#: that cannot be called.
#:
#: Chosen to span the range rather than to be exhaustive: the best, the sensible
#: default, and three that cost between a fifteenth and a fiftieth of it, because
#: this is billed to Alex per message and most of what he asks the coach is
#: parsing and phrasing over numbers Python already computed.
CURATED: tuple[str, ...] = (
    "anthropic/claude-opus-5",
    "anthropic/claude-sonnet-5",
    "anthropic/claude-haiku-4.5",
    "openai/gpt-4.1-mini",
    "google/gemini-2.5-flash",
    "meta-llama/llama-3.3-70b-instruct",
)

#: The one the app starts on. Sonnet rather than Opus: every hard computation —
#: progression, plate maths, week placement — is done in Python before the model
#: sees it, and Alex is standing between two sets while it answers.
DEFAULT_MODEL = "anthropic/claude-sonnet-5"


@dataclass(frozen=True)
class Model:
    """One row of the catalogue, in the units a screen wants."""

    id: str
    name: str
    context: int
    #: US dollars per MILLION tokens. OpenRouter quotes per token, which renders
    #: as "$0.000003" on a phone and tells nobody anything.
    prompt_price: float
    completion_price: float
    tools: bool = True
    #: Si `architecture.input_modalities` trae "image": el modelo puede mirar
    #: una foto de progreso. El desplegable lo marca con 📷 y `Coach.ask`
    #: rehúsa adjuntar una imagen a un modelo que no la vería.
    vision: bool = False

    @property
    def vendor(self) -> str:
        return self.id.split("/", 1)[0] if "/" in self.id else ""

    @property
    def short(self) -> str:
        """`anthropic/claude-opus-5` → `claude-opus-5`. The vendor is the prefix."""
        return self.id.split("/", 1)[-1]

    def price_label(self) -> str:
        return f"${self.prompt_price:g} / ${self.completion_price:g} por M"

    def cost_of(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * self.prompt_price + completion_tokens * self.completion_price
        ) / 1_000_000


def _price(raw: Any) -> float:
    """Dollars per token → dollars per million. Anything unparseable is 0.

    Free models really do quote `"0"`, and a couple of entries quote `"-1"` for
    "ask the provider". Both come back as 0 rather than as an exception: a price
    this module cannot read must not stop the dropdown from opening.
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, value) * 1_000_000


def parse_models(payload: Any) -> list[Model]:
    """The catalogue JSON → `Model`s that can actually run the coach.

    Pure, so the parsing is testable against a recorded payload with no network.
    Anything malformed is skipped rather than raised on: one bad row out of 417
    must not empty the list.
    """
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except ValueError:
            return []
    rows = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []

    out: list[Model] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ident = row.get("id")
        if not ident:
            continue
        if "tools" not in (row.get("supported_parameters") or []):
            continue
        pricing = row.get("pricing") or {}
        try:
            context = int(row.get("context_length") or 0)
        except (TypeError, ValueError):
            context = 0
        modalidades = (row.get("architecture") or {}).get("input_modalities") or []
        out.append(
            Model(
                id=str(ident),
                name=str(row.get("name") or ident),
                context=context,
                prompt_price=_price(pricing.get("prompt")),
                completion_price=_price(pricing.get("completion")),
                vision="image" in modalidades,
            )
        )
    out.sort(key=lambda m: m.id)
    return out


def curated(models: list[Model]) -> list[Model]:
    """The shortlist, in the order of `CURATED`, skipping anything retired."""
    by_id = {m.id: m for m in models}
    return [by_id[i] for i in CURATED if i in by_id]


def search(models: list[Model], query: str, limit: int = 40) -> list[Model]:
    """Substring match over id and name, cheapest first.

    Cheapest first because 348 models do not fit on a phone and the reason to
    open this list at all is usually to spend less. Ties on the completion price,
    which is the half that actually varies with how much the coach says.
    """
    needle = (query or "").strip().lower()
    hits = [m for m in models if not needle or needle in m.id.lower() or needle in m.name.lower()]
    hits.sort(key=lambda m: (m.completion_price, m.prompt_price, m.id))
    return hits[:limit]


# ── fetching, and surviving not being able to ─────────────────────────────

#: Fetched catalogue, kept for the life of the process. Settings is opened
#: rarely and the payload is ~680 KB, so re-fetching on every render would put a
#: visible stall on a screen whose whole job is to show two dropdowns. There is
#: no expiry: a model list that is an hour stale has never been a problem, and a
#: fresh one is a pull-to-refresh away.
_CACHE: list[Model] = []


def clear_cache() -> None:
    _CACHE.clear()


def fetch_models(timeout: float = 20.0) -> list[Model]:
    """The live catalogue. **Raises** on failure — see `models_or_empty`.

    No API key: `/api/v1/models` is public, which is the whole reason the model
    picker works on an install that has not been set up yet. Alex can look at
    what things cost before deciding whether to pay for any of them.
    """
    if _CACHE:
        return list(_CACHE)
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - the APK ships it
        raise RuntimeError("The HTTP client is not installed in this build.") from exc

    with httpx.Client(timeout=timeout) as client:
        response = client.get(
            MODELS_URL, headers={"HTTP-Referer": APP_URL, "X-OpenRouter-Title": APP_TITLE}
        )
    response.raise_for_status()
    modelos = parse_models(response.json())
    if modelos:
        _CACHE.extend(modelos)
    return modelos


def models_or_empty(timeout: float = 20.0) -> tuple[list[Model], bool]:
    """`(models, failed)` — for callers that must render either way.

    A settings screen that raises because a phone is in a basement is a settings
    screen that cannot be used to fix anything, including the setting that
    matters. The flag is returned rather than swallowed so the screen can say
    "could not reach OpenRouter" instead of pretending the catalogue is empty.
    """
    try:
        return (fetch_models(timeout=timeout), False)
    except Exception:
        return ([], True)
