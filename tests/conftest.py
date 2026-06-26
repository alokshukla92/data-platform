"""Shared pytest fixtures and environment defaults for the test suite."""

from __future__ import annotations

import os

import pytest

# Force deterministic, offline-friendly config before importing platform_core.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("API_KEY_SALT", "test-salt")
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "")
os.environ.setdefault("EMBEDDING_DIM", "16")


@pytest.fixture
def deterministic_provider():
    from platform_core.embeddings import DeterministicEmbeddingProvider

    return DeterministicEmbeddingProvider(dim=16)
