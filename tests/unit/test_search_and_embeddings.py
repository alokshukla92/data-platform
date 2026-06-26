import math

import pytest
from platform_core.embeddings import DeterministicEmbeddingProvider
from platform_core.search import _normalise

pytestmark = pytest.mark.unit


def test_normalise_scales_to_unit_range():
    assert _normalise([]) == []
    assert _normalise([5, 5, 5]) == [1.0, 1.0, 1.0]
    out = _normalise([0, 5, 10])
    assert out[0] == 0.0 and out[-1] == 1.0 and 0 < out[1] < 1


def test_deterministic_embeddings_are_stable_and_normalised():
    provider = DeterministicEmbeddingProvider(dim=16)
    a1 = provider.embed(["hello"])[0]
    a2 = provider.embed(["hello"])[0]
    assert a1 == a2  # deterministic
    assert len(a1) == 16
    assert math.isclose(sum(x * x for x in a1) ** 0.5, 1.0, rel_tol=1e-6)  # unit norm


def test_deterministic_embeddings_differ_by_input():
    provider = DeterministicEmbeddingProvider(dim=16)
    assert provider.embed(["a"])[0] != provider.embed(["b"])[0]


def test_embed_empty_returns_empty():
    assert DeterministicEmbeddingProvider(dim=8).embed([]) == []
