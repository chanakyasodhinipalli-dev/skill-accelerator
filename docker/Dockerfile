# syntax=docker/dockerfile:1.7
# Multi-stage build: dependencies are resolved once in the builder and the
# runtime image carries no compilers or build metadata.

# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

# Copy only what pip needs to resolve, so a source-only change does not
# invalidate the dependency layer.
COPY pyproject.toml README.md ./
COPY packages/ ./packages/

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --upgrade pip \
 && for pkg in sa-platform sa-skills sa-tools sa-connectors sa-orchestrator sa-forms sa-api sa-cli; do \
      pip install --no-deps "./packages/$pkg" || exit 1; \
    done \
 && pip install \
      "pydantic>=2.7" "pydantic-settings>=2.3" "PyYAML>=6.0" "httpx>=0.27" \
      "jsonschema>=4.22" "fastapi>=0.115" "uvicorn[standard]>=0.30" \
      "typer>=0.12" "rich>=13.7" "anthropic>=0.69" "mcp>=1.2" \
      "openpyxl>=3.1" "fpdf2>=2.7" "python-docx>=1.1"

# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    SA_ENVIRONMENT=prod \
    SA_LOGGING__FORMAT=json

# curl is present solely for the container healthcheck below.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser skills/ ./skills/
COPY --chown=appuser:appuser examples/ ./examples/

# Never run the agent runtime as root: skills and tools execute code, and a
# non-root user bounds the blast radius of a mistake.
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/health/ready || exit 1

CMD ["uvicorn", "sa_api.app:app", "--host", "0.0.0.0", "--port", "8000", "--log-config", "/dev/null"]
