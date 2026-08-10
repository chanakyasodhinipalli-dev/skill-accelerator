.DEFAULT_GOAL := help
PY ?= python
PACKAGES := sa-platform sa-skills sa-tools sa-connectors sa-orchestrator sa-forms sa-api sa-cli sa-console

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: venv
venv: ## Create .venv (recommended — `install` targets whatever `python` resolves to)
	$(PY) -m venv .venv
	@echo "activate it, then run 'make install':"
	@echo "  source .venv/bin/activate        # macOS/Linux"
	@echo "  .venv\\Scripts\\activate           # Windows"

.PHONY: install
install: ## Install every workspace package in editable mode, plus dev tools
	$(PY) -m pip install --upgrade pip
	@for pkg in $(PACKAGES); do \
	  echo "installing $$pkg"; \
	  $(PY) -m pip install -e packages/$$pkg --no-deps -q || exit 1; \
	done
	$(PY) -m pip install -q \
	  "pydantic>=2.7" "pydantic-settings>=2.3" "PyYAML>=6.0" "httpx>=0.27" \
	  "fastapi>=0.115" "uvicorn[standard]>=0.30" "typer>=0.12" "rich>=13.7" \
	  "jsonschema>=4.22" "openpyxl>=3.1" "fpdf2>=2.7" "python-docx>=1.1" "pypdf>=4.2"
	$(PY) -m pip install -q pytest pytest-asyncio pytest-cov ruff mypy respx
	@echo "done. run 'make check' to verify."

.PHONY: install-llm
install-llm: ## Add the Anthropic SDK and MCP client (optional extras)
	$(PY) -m pip install -q "anthropic>=0.69" "mcp>=1.2"

.PHONY: lint
lint: ## Lint with ruff
	$(PY) -m ruff check packages skills tests examples

.PHONY: format
format: ## Auto-format and fix lint findings
	$(PY) -m ruff format packages skills tests examples
	$(PY) -m ruff check --fix packages skills tests examples

.PHONY: typecheck
typecheck: ## Static type check
	$(PY) -m mypy packages/*/src

.PHONY: test
test: ## Run the test suite
	$(PY) -m pytest

.PHONY: cov
cov: ## Run tests with a coverage report
	$(PY) -m pytest --cov --cov-report=term-missing --cov-report=html

.PHONY: check
check: lint test ## Lint and test — the gate CI enforces

.PHONY: verify-skills
verify-skills: ## Run the skill contract checks
	$(PY) -m sa_cli.main skills verify

.PHONY: doctor
doctor: ## Check that the deployment is wired up correctly
	$(PY) -m sa_cli.main doctor

.PHONY: serve
serve: ## Run the API with auto-reload
	$(PY) -m uvicorn sa_api.app:app --reload --host 0.0.0.0 --port 8000

.PHONY: ui
ui: ## Run the operator console (mounts the API in-process on :8100)
	$(PY) -m sa_console.main

.PHONY: ui-remote
ui-remote: ## Run the console against a remote API, e.g. make ui-remote API=https://sa.internal
	$(PY) -m sa_console.main --api $(API)

.PHONY: docker-build
docker-build: ## Build the container image
	docker build -f docker/Dockerfile -t skill-accelerator:local .

.PHONY: docker-up
docker-up: ## Start the stack with docker compose
	docker compose -f docker/docker-compose.yml up --build

.PHONY: clean
clean: ## Remove build and test artefacts
	@$(PY) -c "import shutil,pathlib; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
	@$(PY) -c "import shutil; [shutil.rmtree(d, ignore_errors=True) for d in ('.pytest_cache','.ruff_cache','.mypy_cache','htmlcov','dist','build')]"
	@echo "cleaned."
