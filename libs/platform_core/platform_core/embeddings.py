"""Pluggable embedding providers.

The :class:`EmbeddingProvider` interface decouples the rest of the platform from any
specific model/vendor. The default ``LocalEmbeddingProvider`` runs sentence-transformers
on-box (zero API cost, reproducible); ``OpenAIEmbeddingProvider`` is a drop-in swap via
``EMBEDDING_PROVIDER=openai`` without touching call sites.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from functools import lru_cache

from .config import EmbeddingProvider as ProviderEnum
from .config import Settings, get_settings
from .logging import get_logger
from .telemetry import EMBEDDINGS_GENERATED_TOTAL

log = get_logger(__name__)


class EmbeddingProvider(ABC):
    dim: int
    name: str

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text (batched)."""


class LocalEmbeddingProvider(EmbeddingProvider):
    """sentence-transformers model loaded lazily and cached for the process lifetime."""

    def __init__(self, model_name: str, dim: int) -> None:
        self.name = "local"
        self.model_name = model_name
        self.dim = dim
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            log.info("loading_embedding_model", model=self.model_name)
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        EMBEDDINGS_GENERATED_TOTAL.labels(provider=self.name).inc(len(texts))
        return [v.tolist() for v in vectors]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_name: str, dim: int, api_key: str) -> None:
        self.name = "openai"
        self.model_name = model_name
        self.dim = dim
        self._api_key = api_key

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        from openai import OpenAI  # imported lazily; only needed when provider=openai

        client = OpenAI(api_key=self._api_key)
        resp = client.embeddings.create(model=self.model_name, input=texts)
        EMBEDDINGS_GENERATED_TOTAL.labels(provider=self.name).inc(len(texts))
        return [d.embedding for d in resp.data]


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Hash-based deterministic vectors. Used in unit tests so CI needs no model download."""

    def __init__(self, dim: int) -> None:
        self.name = "deterministic"
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            digest = hashlib.sha256(t.encode()).digest()
            raw = [(digest[i % len(digest)] / 255.0) for i in range(self.dim)]
            norm = sum(x * x for x in raw) ** 0.5 or 1.0
            out.append([x / norm for x in raw])
        return out


@lru_cache
def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    settings = settings or get_settings()
    if settings.embedding_provider == ProviderEnum.OPENAI:
        if not settings.openai_api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is unset")
        return OpenAIEmbeddingProvider(
            settings.embedding_model, settings.embedding_dim, settings.openai_api_key
        )
    return LocalEmbeddingProvider(settings.embedding_model, settings.embedding_dim)
