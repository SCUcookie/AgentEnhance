#!/usr/bin/env python3
"""Deterministic retrieval and evidence-budget core for Mem-Gallery controls.

This module is intentionally free of model and network dependencies.  Endpoint
clients and the numerical runner remain separate, so this core can be audited
with synthetic fixtures before the frozen dataset and model gates are released.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Callable, Iterable, Mapping, Sequence


CONTROL_METHODS = {
    "no-memory",
    "full-memory-text",
    "full-memory-mm",
    "fifo-recent",
    "bm25",
    "naive-rag",
    "hybrid-rag",
}
WORD_PATTERN = re.compile(r"\w+", flags=re.UNICODE)
BM25_K1 = 1.5
BM25_B = 0.75
BM25_EPSILON = 0.25
HYBRID_CANDIDATES = 20
RRF_CONSTANT = 60


def unicode_word_tokens(text: str) -> list[str]:
    """Match the frozen lowercase Unicode-word tokenization contract."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return WORD_PATTERN.findall(text.casefold())


def _validate_records(records: Sequence[Mapping[str, object]]) -> None:
    ids: set[str] = set()
    chronological: set[int] = set()
    for record in records:
        memory_id = record.get("memory_id")
        index = record.get("chronological_index")
        text = record.get("text")
        images = record.get("image_ids", [])
        if not isinstance(memory_id, str) or not memory_id or memory_id in ids:
            raise ValueError("memory_id values must be unique nonempty strings")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index in chronological:
            raise ValueError("chronological_index values must be unique nonnegative integers")
        if not isinstance(text, str):
            raise ValueError("record text must be a string")
        if not isinstance(images, list) or any(not isinstance(item, str) or not item for item in images):
            raise ValueError("image_ids must be a list of nonempty strings")
        if len(images) != len(set(images)):
            raise ValueError("image_ids must be unique within a record")
        ids.add(memory_id)
        chronological.add(index)


def bm25_okapi_scores(
    documents: Sequence[Sequence[str]],
    query: Sequence[str],
    *,
    k1: float = BM25_K1,
    b: float = BM25_B,
    epsilon: float = BM25_EPSILON,
) -> list[float]:
    """Reproduce rank_bm25.BM25Okapi default scoring without a runtime import."""
    if k1 <= 0 or not 0 <= b <= 1 or epsilon < 0:
        raise ValueError("invalid BM25 parameters")
    if not documents:
        return []
    if any(not isinstance(document, Sequence) or isinstance(document, (str, bytes)) for document in documents):
        raise TypeError("documents must be token sequences")
    lengths = [len(document) for document in documents]
    average_length = sum(lengths) / len(lengths)
    document_frequencies: Counter[str] = Counter()
    term_frequencies: list[Counter[str]] = []
    for document in documents:
        frequencies = Counter(document)
        term_frequencies.append(frequencies)
        document_frequencies.update(frequencies.keys())

    raw_idf: dict[str, float] = {}
    negative_terms: list[str] = []
    for token, frequency in document_frequencies.items():
        value = math.log(len(documents) - frequency + 0.5) - math.log(frequency + 0.5)
        raw_idf[token] = value
        if value < 0:
            negative_terms.append(token)
    average_idf = sum(raw_idf.values()) / len(raw_idf) if raw_idf else 0.0
    floor = epsilon * average_idf
    for token in negative_terms:
        raw_idf[token] = floor

    scores = [0.0] * len(documents)
    for token in query:
        idf = raw_idf.get(token, 0.0)
        for position, frequencies in enumerate(term_frequencies):
            frequency = frequencies.get(token, 0)
            if frequency == 0:
                continue
            normalization = frequency + k1 * (
                1.0 - b + b * lengths[position] / average_length
            )
            scores[position] += idf * frequency * (k1 + 1.0) / normalization
    return scores


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("cosine vectors must have the same nonzero dimension")
    if any(not math.isfinite(float(value)) for value in (*left, *right)):
        raise ValueError("cosine vectors must contain only finite values")
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("cosine vectors must have nonzero norm")
    return dot / (left_norm * right_norm)


def _rank_by_scores(
    records: Sequence[Mapping[str, object]], scores: Sequence[float], limit: int
) -> list[Mapping[str, object]]:
    if len(records) != len(scores):
        raise ValueError("record and score counts differ")
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    if any(not math.isfinite(float(score)) for score in scores):
        raise ValueError("ranking scores must be finite")
    order = sorted(
        range(len(records)),
        key=lambda index: (-float(scores[index]), int(records[index]["chronological_index"])),
    )
    return [records[index] for index in order[:limit]]


def retrieve_control(
    method_id: str,
    records: Sequence[Mapping[str, object]],
    query: str,
    *,
    top_k: int = 10,
    dense_document_vectors: Sequence[Sequence[float]] | None = None,
    dense_query_vector: Sequence[float] | None = None,
) -> list[Mapping[str, object]]:
    """Return the prospectively ranked evidence records for one frozen control."""
    if method_id not in CONTROL_METHODS:
        raise ValueError(f"unregistered control method: {method_id}")
    if top_k < 0:
        raise ValueError("top_k must be nonnegative")
    _validate_records(records)
    chronological = sorted(records, key=lambda item: int(item["chronological_index"]))
    if method_id == "no-memory":
        return []
    if method_id in {"full-memory-text", "full-memory-mm"}:
        return chronological
    if method_id == "fifo-recent":
        return chronological[-top_k:]

    lexical_scores = bm25_okapi_scores(
        [unicode_word_tokens(str(record["text"])) for record in records],
        unicode_word_tokens(query),
    )
    if method_id == "bm25":
        return _rank_by_scores(records, lexical_scores, top_k)

    if dense_document_vectors is None or dense_query_vector is None:
        raise ValueError(f"{method_id} requires frozen dense vectors")
    if len(dense_document_vectors) != len(records):
        raise ValueError("dense document vector count differs from record count")
    dense_scores = [cosine_similarity(vector, dense_query_vector) for vector in dense_document_vectors]
    if method_id == "naive-rag":
        return _rank_by_scores(records, dense_scores, top_k)

    lexical = _rank_by_scores(records, lexical_scores, min(HYBRID_CANDIDATES, len(records)))
    dense = _rank_by_scores(records, dense_scores, min(HYBRID_CANDIDATES, len(records)))
    ranks: dict[str, dict[str, int]] = {}
    by_id = {str(record["memory_id"]): record for record in records}
    for component, ranked in (("lexical", lexical), ("dense", dense)):
        for rank, record in enumerate(ranked, start=1):
            ranks.setdefault(str(record["memory_id"]), {})[component] = rank
    fused: list[tuple[float, int, int, str]] = []
    for memory_id, components in ranks.items():
        score = sum(1.0 / (RRF_CONSTANT + rank) for rank in components.values())
        best_rank = min(components.values())
        chronological_index = int(by_id[memory_id]["chronological_index"])
        fused.append((-score, best_rank, chronological_index, memory_id))
    fused.sort()
    return [by_id[memory_id] for _, _, _, memory_id in fused[:top_k]]


def pack_evidence(
    records: Sequence[Mapping[str, object]],
    token_count: Callable[[str], int],
    *,
    token_image_budget: int = 4096,
    image_token_cost: int = 256,
    max_images: int | None = None,
    newest_preserving: bool = False,
) -> tuple[list[Mapping[str, object]], dict[str, int]]:
    """Apply N_text + image_token_cost*N_images without partial records."""
    _validate_records(records)
    if token_image_budget < 0 or image_token_cost < 0:
        raise ValueError("evidence budgets must be nonnegative")
    if max_images is not None and max_images < 0:
        raise ValueError("max_images must be nonnegative")
    candidates: Iterable[Mapping[str, object]] = records
    if newest_preserving:
        candidates = sorted(records, key=lambda item: int(item["chronological_index"]), reverse=True)
    selected: list[Mapping[str, object]] = []
    text_tokens = 0
    image_count = 0
    for record in candidates:
        record_text_tokens = token_count(str(record["text"]))
        if not isinstance(record_text_tokens, int) or isinstance(record_text_tokens, bool) or record_text_tokens < 0:
            raise ValueError("token_count must return a nonnegative integer")
        record_images = len(record.get("image_ids", []))
        if max_images is not None and image_count + record_images > max_images:
            continue
        projected = text_tokens + record_text_tokens + image_token_cost * (image_count + record_images)
        if projected > token_image_budget:
            continue
        selected.append(record)
        text_tokens += record_text_tokens
        image_count += record_images
    if newest_preserving:
        selected.sort(key=lambda item: int(item["chronological_index"]))
    return selected, {
        "text_tokens": text_tokens,
        "images": image_count,
        "image_token_cost": image_token_cost * image_count,
        "total_budget_units": text_tokens + image_token_cost * image_count,
    }

