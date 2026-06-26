"""Text utilities: content hashing and chunking for embedding."""

from __future__ import annotations

import hashlib
import re

_WS = re.compile(r"\s+")


def content_hash(text: str) -> str:
    return hashlib.sha256(_WS.sub(" ", text).strip().encode()).hexdigest()


def estimate_tokens(text: str) -> int:
    # Rough heuristic (~4 chars/token) good enough for budgeting/metrics.
    return max(1, len(text) // 4)


def chunk_text(text: str, *, chunk_size: int = 800, overlap: int = 120) -> list[str]:
    """Sentence-aware sliding-window chunker.

    Splits on sentence boundaries, then packs sentences into windows of ~``chunk_size``
    characters with ``overlap`` characters carried over to preserve context across chunks.
    """
    text = _WS.sub(" ", text).strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= chunk_size:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            if overlap and chunks:
                tail = chunks[-1][-overlap:]
                current = f"{tail} {sentence}".strip()
            else:
                current = sentence
    if current:
        chunks.append(current)
    return chunks
