#!/usr/bin/env python3
"""Result-free blind overlay for five eligible Causal-LoCoMo controls.

No transport is implemented here.  Real answer and embedding calls must be
injected by a later frozen lifecycle controller.  The module only composes
blind prompts, reproduces the eligible upstream selection rules, and emits one
denominator-preserving row per requested method/example/seed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Callable, Mapping, Sequence

from scripts.causal_locomo_inference_view import assert_blind_view


SCHEMA_VERSION = "agentenhance.causal_locomo_prediction.v1"
ANSWER_MODEL = "Qwen3-VL-8B-Instruct"
ANSWER_TEMPERATURE = 0.0
ANSWER_MAX_OUTPUT_TOKENS = 600
RETRIEVAL_TOP_K = 5
ELIGIBLE_METHODS = (
    "cmi-no-memory",
    "cmi-full-history",
    "cmi-vector-memory",
    "cmi-summary-memory",
    "cmi-graph-memory",
)
BLOCKED_METHODS = frozenset({"cmi-reflection-memory", "cmi"})
TOKEN_RE = re.compile(r"[A-Za-z0-9']+")

AnswerFunction = Callable[[Mapping[str, Any]], Mapping[str, Any]]
EmbeddingFunction = Callable[[Sequence[str], int], Mapping[str, Any]]


class OverlayError(RuntimeError):
    """A method/example overlay failed without substituting a fallback."""


def canonical_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text or "")]


def keyword_overlap(a: str, b: str) -> float:
    a_tokens = set(tokenize(a))
    b_tokens = set(tokenize(b))
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        raise OverlayError("embedding vectors must be nonempty and dimension matched")
    values = [float(value) for value in (*a, *b)]
    if not all(math.isfinite(value) for value in values):
        raise OverlayError("embedding vector contains a non-finite value")
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    norm_a = math.sqrt(sum(float(x) * float(x) for x in a))
    norm_b = math.sqrt(sum(float(y) * float(y) for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        raise OverlayError("embedding vector has zero norm")
    score = dot / (norm_a * norm_b)
    if not math.isfinite(score):
        raise OverlayError("cosine similarity is non-finite")
    return score


def _accepted_call(result: Mapping[str, Any], category: str) -> dict[str, Any]:
    call = result.get("call")
    if not isinstance(call, Mapping):
        raise OverlayError(f"{category} result lacks a call record")
    if (
        call.get("status") != "ACCEPTED"
        or call.get("attempts") != 1
        or call.get("retry_count") != 0
    ):
        raise OverlayError(f"{category} call is not one-shot accepted")
    return dict(call)


def _embed_one(text: str, seed: int, embed: EmbeddingFunction) -> tuple[list[float], dict[str, Any]]:
    result = embed([text], seed)
    if not isinstance(result, Mapping):
        raise OverlayError("embedding result must be an object")
    call = _accepted_call(result, "embedding")
    vectors = result.get("vectors")
    if not isinstance(vectors, list) or len(vectors) != 1 or not isinstance(vectors[0], list):
        raise OverlayError("embedding result must contain exactly one vector")
    vector = [float(value) for value in vectors[0]]
    if not vector or not all(math.isfinite(value) for value in vector):
        raise OverlayError("embedding result contains an invalid vector")
    return vector, call


def _format_memories(memories: Sequence[Mapping[str, Any]]) -> str:
    if not memories:
        return "(none)"
    return "\n".join(f"- {memory['memory_id']}: {memory['content']}" for memory in memories)


def render_prompt(
    view: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
    prompt_kind: str,
) -> str:
    task = view["current_task"]["instruction"]
    if prompt_kind == "no_memory":
        return (
            "You are a careful assistant. Complete the current task.\n\n"
            f"Current task:\n{task}\n\nReturn only the final response."
        )
    if prompt_kind == "full_history":
        sessions = "\n".join(
            f"- {session['timestamp']}: {session['content']}" for session in view["past_sessions"]
        )
        return (
            "You are an assistant with access to the user's past sessions.\n\n"
            f"Past sessions:\n{sessions}\n\nCurrent task:\n{task}"
        )
    if prompt_kind != "agent":
        raise OverlayError(f"unknown prompt kind: {prompt_kind}")
    return (
        "You are a careful assistant. Complete the current task using only memories that are relevant and reliable.\n\n"
        f"Retrieved memories:\n{_format_memories(evidence)}\n\n"
        f"Current task:\n{task}\n\nReturn only the final response."
    )


def _vector_select(
    view: Mapping[str, Any], seed: int, embed: EmbeddingFunction
) -> tuple[list[Mapping[str, Any]], list[dict[str, Any]]]:
    query_vector, query_call = _embed_one(view["current_task"]["instruction"], seed, embed)
    calls = [query_call]
    scored: list[tuple[float, int, Mapping[str, Any]]] = []
    for index, memory in enumerate(view["memory_bank"]):
        memory_vector, call = _embed_one(memory["content"], seed, embed)
        calls.append(call)
        scored.append((cosine_similarity(query_vector, memory_vector), index, memory))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in scored[:RETRIEVAL_TOP_K]], calls


def _graph_select(view: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    query = view["current_task"]["instruction"]
    query_tokens = set(tokenize(query))
    scored: list[tuple[float, int, Mapping[str, Any]]] = []
    for index, memory in enumerate(view["memory_bank"]):
        concepts = {token for token in tokenize(memory["content"]) if len(token) > 3}
        connected = len(query_tokens & concepts)
        score = connected + keyword_overlap(query, memory["content"])
        scored.append((score, index, memory))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in scored[:RETRIEVAL_TOP_K]]


def _selection(
    view: Mapping[str, Any],
    method_id: str,
    seed: int,
    embed: EmbeddingFunction | None,
) -> tuple[list[Mapping[str, Any]], list[str], str, list[dict[str, Any]]]:
    memories = list(view["memory_bank"])
    if method_id == "cmi-no-memory":
        return [], [], "no_memory", []
    if method_id == "cmi-full-history":
        return memories, [memory["memory_id"] for memory in memories], "full_history", []
    if method_id == "cmi-vector-memory":
        if embed is None:
            raise OverlayError("vector memory requires the frozen embedding endpoint")
        selected, calls = _vector_select(view, seed, embed)
        return selected, [memory["memory_id"] for memory in selected], "agent", calls
    if method_id == "cmi-summary-memory":
        content = " ".join(memory["content"] for memory in memories[:8]) or "No durable memory is available."
        summary = {"memory_id": "summary", "content": content}
        return [summary], [memory["memory_id"] for memory in memories], "agent", []
    if method_id == "cmi-graph-memory":
        selected = _graph_select(view)
        return selected, [memory["memory_id"] for memory in selected], "agent", []
    raise OverlayError(f"unregistered eligible method: {method_id}")


def run_method(
    view: Mapping[str, Any],
    *,
    method_id: str,
    seed: int,
    answer: AnswerFunction,
    embed: EmbeddingFunction | None = None,
) -> dict[str, Any]:
    """Emit one ACCEPTED or FAILED row; never substitute a fallback."""
    assert_blind_view(view)
    if seed not in {0, 1, 2}:
        raise OverlayError("seed must be one of 0, 1, or 2")
    if method_id in BLOCKED_METHODS:
        raise OverlayError(f"method is protocol-blocked from main execution: {method_id}")
    if method_id not in ELIGIBLE_METHODS:
        raise OverlayError(f"unknown method: {method_id}")
    base = {
        "schema_version": SCHEMA_VERSION,
        "example_id": view["example_id"],
        "task_family": view["task_family"],
        "method_id": method_id,
        "seed": seed,
    }
    calls: list[dict[str, Any]] = []
    try:
        evidence, selected_ids, prompt_kind, embedding_calls = _selection(view, method_id, seed, embed)
        calls.extend(embedding_calls)
        prompt = render_prompt(view, evidence, prompt_kind)
        request = {
            "model": ANSWER_MODEL,
            "temperature": ANSWER_TEMPERATURE,
            "max_tokens": ANSWER_MAX_OUTPUT_TOKENS,
            "seed": seed,
            "messages": [{"role": "user", "content": prompt}],
        }
        answer_result = answer(request)
        if not isinstance(answer_result, Mapping):
            raise OverlayError("answer result must be an object")
        calls.append(_accepted_call(answer_result, "answer"))
        response = answer_result.get("text")
        if not isinstance(response, str) or not response.strip():
            raise OverlayError("answer result is empty")
        all_ids = [memory["memory_id"] for memory in view["memory_bank"]]
        selected_set = set(selected_ids)
        return {
            **base,
            "status": "ACCEPTED",
            "response": response,
            "selected_memory_ids": selected_ids,
            "retrieved_memory_ids": selected_ids,
            "rejected_memory_ids": [memory_id for memory_id in all_ids if memory_id not in selected_set],
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "calls": calls,
            "failure_kind": None,
            "error_type": None,
            "error": None,
        }
    except Exception as exc:  # one retained denominator row, no fallback or retry
        failure_record = getattr(exc, "record", None)
        if isinstance(failure_record, Mapping):
            calls.append(dict(failure_record))
        return {
            **base,
            "status": "FAILED",
            "response": "",
            "selected_memory_ids": [],
            "retrieved_memory_ids": [],
            "rejected_memory_ids": [memory["memory_id"] for memory in view["memory_bank"]],
            "prompt_sha256": None,
            "calls": calls,
            "failure_kind": "METHOD_EXECUTION",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def protocol_blocked_row(view: Mapping[str, Any], *, method_id: str, seed: int) -> dict[str, Any]:
    """Represent a registered but evaluator-leaking method without executing it."""
    assert_blind_view(view)
    if method_id not in BLOCKED_METHODS:
        raise OverlayError(f"method is not protocol-blocked: {method_id}")
    if seed not in {0, 1, 2}:
        raise OverlayError("seed must be one of 0, 1, or 2")
    reasons = {
        "cmi-reflection-memory": "upstream reflection_memory consumes memory.label",
        "cmi": "upstream cmi consumes gold IDs, memory labels, and answer scoring criteria",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "example_id": view["example_id"],
        "task_family": view["task_family"],
        "method_id": method_id,
        "seed": seed,
        "status": "FAILED",
        "response": "",
        "selected_memory_ids": [],
        "retrieved_memory_ids": [],
        "rejected_memory_ids": [memory["memory_id"] for memory in view["memory_bank"]],
        "prompt_sha256": None,
        "calls": [],
        "failure_kind": "PROTOCOL_BLOCKED",
        "error_type": "ProtocolBlockedGoldLeak",
        "error": reasons[method_id],
    }
