# ─── hfpclawer Development Makefile ───────────────
# Targets:
#   make dev       — editable install (uv)
#   make lint      — ruff check
#   make format    — ruff format
#   make test      — pytest (unit)
#   make test-all  — all tests
#   make type      — pyright
#   make check     — lint + type + test
#   make clean     — clean build artifacts

.PHONY: dev lint format test test-all type check clean

dev:
	uv pip install -e ".[dev]"

lint:
	ruff check .

format:
	ruff format .
	ruff check --fix .

test:
	python -m pytest tests/ -x --timeout=30

test-all:
	python -m pytest tests/ -v --timeout=30

type:
	pyright .

check: lint type test

clean:
	rm -rf build/ dist/ *.egg-info/ .pytest_cache/ .ruff_cache/ __pycache__/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
