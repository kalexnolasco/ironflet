# Puntos de entrada de desarrollo. Esta app es la APK: en el escritorio solo
# se abre para desarrollar y para correr los tests.

VENV := .venv/bin
PY   := $(VENV)/python

.PHONY: deps check test lint fmt run apk install

## deps: instalar dependencias de desarrollo.
#
# En 0.12 esto tenía un segundo paso obligatorio (vendorizar CanvasKit dentro
# de flet_web) y el ORDEN era load-bearing. Con el modo web jubilado no hay
# CanvasKit que vendorizar ni orden que respetar: un `uv sync` y ya.
deps:
	uv sync --group dev

## check: lo mismo que corre CI, en el mismo orden.
check: lint test

lint:
	uv run ruff check .
	uv run ruff format --check .

## test: la suite entera sobre SQLite. Sin Docker, sin saltarse nada.
test:
	$(PY) -m pytest -q

fmt:
	uv run ruff format .
	uv run ruff check --fix .

## run: la app en el escritorio, contra el SQLite local. Solo para desarrollar.
run:
	$(PY) main.py

## apk: compilar el APK con las tres ABIs (trampa 23: las tres, o exactamente una).
#
# `rm -rf build` antes, siempre: borrar solo `build/flutter` deja a flet con
# estado a medias y falla con un FileNotFoundError que no dice qué pasa.
apk:
	rm -rf build
	$(VENV)/flet build apk -v

## install: el APK recién compilado, al móvil o al emulador conectado.
install:
	adb install -r build/apk/app-release.apk
