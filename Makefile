# Development entry points. The order inside `deps` matters — see below.

VENV := .venv/bin
PY   := $(VENV)/python

.PHONY: deps check test lint fmt run deploy

## deps: install everything the app needs, in the one order that works.
#
# `uv sync` alone is not enough. Flet's web client (`flet-web`) is now declared
# through the `flet[all]` extra so the lockfile carries it, but the CanvasKit
# assets are NOT a Python package: they are ~12 MB fetched by
# scripts/vendor_canvaskit.py into the *installed* flet_web, plus a patch to
# flutter_bootstrap.js. Reinstalling flet_web wipes both, and the app silently
# goes back to downloading CanvasKit from Google — which fails in a gym with no
# signal. So: sync first, vendor second, always.
deps:
	uv sync --group dev
	$(PY) scripts/vendor_canvaskit.py

## check: everything CI runs, in the same order.
check: lint test

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	$(PY) -m pytest -q

fmt:
	uv run ruff format .
	uv run ruff check --fix .

## run: web mode on the LAN, the way it is actually deployed.
run:
	IRONFLET_WEB=1 $(PY) main.py

## deploy: restart the three services in the safe order.
#
# The bot and the panel hold live SQLAlchemy pools against the shared database.
# Anything touching the schema has to stop them first, or an ALTER takes an
# ACCESS EXCLUSIVE lock and their next query blocks and fails.
deploy:
	systemctl --user stop entrenador-bot entrenador-panel
	systemctl --user restart ironflet-web
	systemctl --user start entrenador-bot entrenador-panel
	@sleep 8
	@systemctl --user is-active ironflet-web entrenador-bot entrenador-panel
	@journalctl --user -u ironflet-web -n 15 --no-pager -o cat
