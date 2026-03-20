.PHONY: dev run-lite docs docs-serve lint test build build-lite build-dmg clean

# Run the app in development mode (Standard — all backends)
dev:
	uv sync --all-extras
	uv run python -m wenzi

# Run Lite version (Apple Speech + Remote API only)
run-lite:
	test -d .venv-lite || uv venv .venv-lite
	UV_PROJECT_ENVIRONMENT=.venv-lite uv sync
	WENZI_VERSION=lite UV_PROJECT_ENVIRONMENT=.venv-lite uv run python -m wenzi

# Build HTML documentation from docs/*.md
docs:
	uv run --with markdown python scripts/build_docs.py

# Serve the site locally
docs-serve: docs
	@echo "Serving at http://localhost:8003"
	python3 -m http.server 8003 -d site

# Lint with ruff
lint:
	uv run ruff check

# Run tests with coverage
test:
	uv run pytest tests/ -v --cov=wenzi

# Build the .app bundle (Standard)
build:
	./scripts/build.sh

# Build the Lite .app bundle
build-lite:
	./scripts/build-lite.sh

# Build the .dmg installer
build-dmg:
	./scripts/build-dmg.sh

# Remove build artifacts
clean:
	rm -rf build/ dist/
