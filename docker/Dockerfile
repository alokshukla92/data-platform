# syntax=docker/dockerfile:1.7
# Multi-stage build. One image serves every service/worker; the runtime command
# (set in compose / K8s) selects which process to run.

FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

# ---- builder: install deps into a venv ----
FROM base AS builder
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml README.md ./
COPY libs ./libs
# Install the platform_core package + all runtime deps.
RUN pip install --upgrade pip && pip install .

# ---- runtime: non-root, slim ----
FROM base AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app:/app/libs/platform_core"
COPY --from=builder /opt/venv /opt/venv
COPY . /app

# Pre-download the default embedding model so pods start warm and don't hit the
# network on first request (override with EMBEDDING_MODEL at build time if needed).
ARG PREFETCH_MODEL=true
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RUN if [ "$PREFETCH_MODEL" = "true" ]; then \
      python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')" || true; \
    fi

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
# Default command runs the gateway; compose/K8s override per service.
CMD ["gunicorn", "services.gateway.app.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-b", "0.0.0.0:8000", "--workers", "2", "--timeout", "60", \
     "--graceful-timeout", "30", "--max-requests", "1000", "--max-requests-jitter", "100"]
