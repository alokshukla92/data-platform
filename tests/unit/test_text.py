import pytest
from platform_core.text import chunk_text, content_hash, estimate_tokens

pytestmark = pytest.mark.unit


def test_content_hash_is_whitespace_insensitive():
    assert content_hash("hello   world") == content_hash("hello world")
    assert content_hash("a") != content_hash("b")


def test_estimate_tokens_minimum_one():
    assert estimate_tokens("") == 1
    assert estimate_tokens("x" * 40) >= 10


def test_chunk_text_empty():
    assert chunk_text("") == []


def test_chunk_text_respects_size_and_overlap():
    text = " ".join(f"Sentence number {i}." for i in range(200))
    chunks = chunk_text(text, chunk_size=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(c) <= 400 for c in chunks)  # size + overlap headroom


def test_chunk_text_single_short():
    assert chunk_text("Just one sentence.") == ["Just one sentence."]
