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

# ---- builder: install deps into a venv (cached independently of app source) ----
FROM base AS builder
# Enable pip's wheel cache in this stage (overrides the base image's NO_CACHE_DIR)
# so the BuildKit cache mount below can persist downloaded wheels (e.g. torch).
ENV PIP_NO_CACHE_DIR=0
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# Only the dependency manifest is copied here. A *stub* platform_core package lets
# hatchling build metadata without the real source, so editing application code
# does NOT invalidate this (expensive) dependency layer.
COPY pyproject.toml README.md ./
RUN mkdir -p libs/platform_core/platform_core \
    && printf '"""build stub - real source is provided via PYTHONPATH at runtime"""\n' \
       > libs/platform_core/platform_core/__init__.py
# BuildKit cache mount keeps the pip wheel cache across builds, so a dependency
# change re-downloads only what actually changed instead of all of PyTorch.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && pip install .

# ---- runtime: non-root, slim ----
FROM base AS runtime
# Fixed model cache location so a baked-in model is found by the non-root runtime
# user (HF/sentence-transformers default to $HOME/.cache, which differs per user).
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app:/app/libs/platform_core" \
    HF_HOME="/opt/hf-cache" \
    SENTENCE_TRANSFORMERS_HOME="/opt/hf-cache"
COPY --from=builder /opt/venv /opt/venv
COPY . /app

# Pre-download the default embedding model into HF_HOME so pods start warm and
# never hit the network on first request (override EMBEDDING_MODEL at build time).
ARG PREFETCH_MODEL=true
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RUN mkdir -p /opt/hf-cache && \
    if [ "$PREFETCH_MODEL" = "true" ]; then \
      python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"; \
    fi

# chown both the app and the model cache so appuser can read the baked model.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /opt/hf-cache
USER appuser

EXPOSE 8000
# Default command runs the gateway; compose/K8s override per service.
CMD ["gunicorn", "services.gateway.app.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-b", "0.0.0.0:8000", "--workers", "2", "--timeout", "60", \
     "--graceful-timeout", "30", "--max-requests", "1000", "--max-requests-jitter", "100"]
