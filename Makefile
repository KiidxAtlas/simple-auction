.PHONY: help install-dev format lint test icon build-standalone release update clean

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Common targets:"
	@echo "  install-dev       Install the app and dev tools (uv sync)"
	@echo "  format            Format the repository with Ruff"
	@echo "  lint              Run Ruff"
	@echo "  test              Run test suite (pytest)"
	@echo "  icon              Regenerate assets/icon.png and icon.ico"
	@echo "  build-standalone  Build standalone app via scripts/build_standalone.py"
	@echo "  release VERSION=x.y.z  Tag and push a release (scripts/make_release.sh)"
	@echo "  update            Update a pipx/pip install from GitHub (scripts/update.sh)"
	@echo "  clean             Remove build artifacts"

install-dev:
	uv sync --extra build

format:
	uv run ruff format .

lint:
	uv run ruff check .

test:
	QT_QPA_PLATFORM=offscreen uv run pytest -q

icon:
	uv run python scripts/gen_icon.py

build-standalone:
	uv run --extra build python scripts/build_standalone.py

release:
	@PY="uv run python" ./scripts/make_release.sh $(VERSION)

update:
	sh ./scripts/update.sh

clean:
	rm -rf build dist *.spec
