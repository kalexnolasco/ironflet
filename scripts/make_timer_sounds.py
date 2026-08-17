"""Generate the rest-timer alert tones into `assets/sounds/`.

The tones are synthesised here instead of downloaded so the repository carries
no third-party audio and no licence question: this file *is* the source, and
the WAVs it writes are a build product that happens to be committed.

    .venv/bin/python scripts/make_timer_sounds.py

Deterministic — pure arithmetic, no randomness — so re-running it reproduces
the committed files byte for byte. `tests/test_timer_sound.py` relies on that
to prove the checked-in assets still match this script.

Why these numbers
-----------------
**3000 Hz for "go", 2000 Hz for the 10-second warning.** Human hearing peaks
between 2 and 4 kHz (that is where the equal-loudness contours dip and why
smoke alarms sit at ~3.1 kHz), and a phone speaker is a few millimetres across:
below roughly 700 Hz it radiates almost nothing. A deep tone is therefore
quieter twice over — the speaker cannot produce it and the ear is less
sensitive to it — which is exactly wrong for a phone lying on a gym floor with
music playing. The two tones are a fifth-and-a-bit apart so the warning is
recognisably *not* the finish, even at a distance.

**Short bursts, not one long note.** A rhythm carries through music better than
a sustained tone, which the ear merges into the background within a second.
"Go" is three bursts with the last one longer; the warning is a single short
blip, so counting alone tells them apart.

**6 ms fade in and out on every burst.** A sine cut off mid-cycle is a step
change: it splatters energy across the whole spectrum and comes out as a click,
which on a small speaker sounds like a fault rather than a beep.

**22 050 Hz, 16-bit mono.** Nyquist is 11 kHz, comfortably above the highest
partial in a 3 kHz sine, and halving the sample rate halves the file. The two
files together are ~27 KB; at 44.1 kHz stereo they would be ~108 KB of an APK
for no audible difference.
"""

from __future__ import annotations

import math
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

#: Nyquist at 11 025 Hz — four times the highest tone here. Anything more is
#: bytes in an APK that no one can hear.
SAMPLE_RATE = 22_050

#: Peak amplitude as a fraction of full scale. Not 1.0: browsers and Android
#: both mix this with whatever else is playing, and a signal that already sits
#: at the rail clips as soon as anything is added to it.
AMPLITUDE = 0.8

#: Raised-cosine attack/release per burst. Long enough to remove the click of a
#: hard edge, short enough that the beep still reads as instant.
FADE_S = 0.006


@dataclass(frozen=True)
class Spec:
    """One alert: a single pitch, played as a pattern of bursts."""

    freq_hz: float
    bursts_s: tuple[float, ...]
    gap_s: float


SOUNDS: dict[str, Spec] = {
    # "Ten seconds": one blip, low enough to be obviously not the finish.
    # 90 ms total, ~3.9 KB.
    "rest_warning": Spec(freq_hz=2000.0, bursts_s=(0.090,), gap_s=0.0),
    # "Go": beep-beep-beeep. The lengthened third burst is the part that reads
    # as an ending rather than as a notification. 540 ms total, ~23 KB.
    "rest_done": Spec(freq_hz=3000.0, bursts_s=(0.110, 0.110, 0.180), gap_s=0.070),
}

ASSETS_SOUNDS = Path(__file__).resolve().parent.parent / "assets" / "sounds"


def _burst(freq_hz: float, seconds: float) -> list[int]:
    """One enveloped sine burst as 16-bit signed samples.

    The envelope is applied by sample index rather than by time so the fade is
    exact at the boundaries: a burst shorter than two fades would otherwise get
    a gain above 1 in the middle and clip.
    """
    total = int(round(seconds * SAMPLE_RATE))
    fade = min(int(round(FADE_S * SAMPLE_RATE)), total // 2)
    step = 2.0 * math.pi * freq_hz / SAMPLE_RATE
    out: list[int] = []
    for i in range(total):
        gain = 1.0
        if fade:
            if i < fade:
                # Raised cosine: starts and ends with zero slope, so there is
                # no discontinuity in the waveform *or* in its derivative.
                gain = 0.5 - 0.5 * math.cos(math.pi * i / fade)
            elif i >= total - fade:
                gain = 0.5 - 0.5 * math.cos(math.pi * (total - 1 - i) / fade)
        # 32767, not 32768: +32768 is not representable in signed 16-bit and
        # would wrap to the most negative sample at every peak.
        out.append(int(round(math.sin(step * i) * gain * AMPLITUDE * 32767)))
    return out


def render(spec: Spec) -> array:
    """The full waveform for one alert, bursts separated by silence."""
    samples = array("h")
    gap = [0] * int(round(spec.gap_s * SAMPLE_RATE))
    for index, seconds in enumerate(spec.bursts_s):
        if index:
            samples.extend(gap)
        samples.extend(_burst(spec.freq_hz, seconds))
    return samples


def write_wav(path: Path, samples: array) -> None:
    """Write mono 16-bit PCM.

    `array("h")` is native-endian and WAV is little-endian; on a big-endian
    host the bytes would come out reversed, so byteswap there rather than
    assume the world is x86.
    """
    import sys

    data = samples[:]
    if sys.byteorder == "big":
        data.byteswap()
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(data.tobytes())


def build(target_dir: Path = ASSETS_SOUNDS) -> dict[str, Path]:
    """Write every tone into `target_dir`. Returns name → path."""
    written: dict[str, Path] = {}
    for name, spec in SOUNDS.items():
        path = target_dir / f"{name}.wav"
        write_wav(path, render(spec))
        written[name] = path
    return written


if __name__ == "__main__":
    for name, path in build().items():
        size = path.stat().st_size
        spec = SOUNDS[name]
        seconds = sum(spec.bursts_s) + spec.gap_s * (len(spec.bursts_s) - 1)
        print(f"{path}  {spec.freq_hz:.0f} Hz  {seconds * 1000:.0f} ms  {size / 1024:.1f} KB")
