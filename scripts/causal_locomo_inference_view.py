#!/usr/bin/env python3
"""Build the evaluation-blind inference view for Causal-LoCoMo.

The released CMI records combine inference inputs and evaluator-only labels in
one JSON object.  This module is deliberately independent from the upstream
agent classes: it exposes only the fields a deployable memory method may see.
Gold labels remain available to the post-hoc evaluator, never to this view.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


SCHEMA_VERSION = "agentenhance.causal_locomo_inference_view.v1"

FORBIDDEN_TOP_LEVEL = frozenset(
    {
        "bad_memory_ids",
        "context_dependent_memory_ids",
        "gold_behavior",
        "gold_memory_ids",
        "intervention_tests",
        "metadata",
        "quality_status",
        "scoring_criteria",
    }
)
FORBIDDEN_MEMORY_FIELDS = frozenset(
    {
        "causal_role",
        "derivation",
        "expected_effect",
        "label",
        "scope",
        "source_candidate_ids",
        "source_dia_ids",
        "source_session_ids",
        "synthetic",
        "type",
    }
)


class InferenceViewError(ValueError):
    """The source record cannot produce a unique, blind inference view."""


def _required_text(container: Mapping[str, Any], key: str, where: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value:
        raise InferenceViewError(f"{where}.{key} must be a nonempty string")
    return value


def _required_int(container: Mapping[str, Any], key: str, where: str) -> int:
    value = container.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise InferenceViewError(f"{where}.{key} must be an integer")
    return value


def _optional_text(container: Mapping[str, Any], key: str, where: str) -> str | None:
    value = container.get(key)
    if value is not None and (not isinstance(value, str) or not value):
        raise InferenceViewError(f"{where}.{key} must be null or a nonempty string")
    return value


def build_inference_view(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new object containing only prospectively allowed input fields."""
    if not isinstance(record, Mapping):
        raise InferenceViewError("record must be an object")
    example_id = _required_text(record, "example_id", "record")
    task_family = _required_text(record, "task_family", "record")

    raw_sessions = record.get("past_sessions")
    if not isinstance(raw_sessions, list):
        raise InferenceViewError("record.past_sessions must be a list")
    sessions: list[dict[str, Any]] = []
    session_ids: set[str] = set()
    last_timestamp: int | None = None
    for index, session in enumerate(raw_sessions):
        if not isinstance(session, Mapping):
            raise InferenceViewError(f"past_sessions[{index}] must be an object")
        where = f"past_sessions[{index}]"
        session_id = _required_text(session, "session_id", where)
        if session_id in session_ids:
            raise InferenceViewError(f"duplicate session_id: {session_id}")
        timestamp = _required_int(session, "timestamp", where)
        if last_timestamp is not None and timestamp < last_timestamp:
            raise InferenceViewError("past_sessions must be chronological")
        session_ids.add(session_id)
        last_timestamp = timestamp
        sessions.append(
            {
                "session_id": session_id,
                "timestamp": timestamp,
                "content": _required_text(session, "content", where),
            }
        )

    current = record.get("current_task")
    if not isinstance(current, Mapping):
        raise InferenceViewError("record.current_task must be an object")
    current_task = {
        "task_id": _required_text(current, "task_id", "current_task"),
        "instruction": _required_text(current, "instruction", "current_task"),
        "recipient_type": _optional_text(current, "recipient_type", "current_task"),
        "domain": _required_text(current, "domain", "current_task"),
    }

    raw_memories = record.get("memory_bank")
    if not isinstance(raw_memories, list) or not raw_memories:
        raise InferenceViewError("record.memory_bank must be a nonempty list")
    memories: list[dict[str, Any]] = []
    memory_ids: set[str] = set()
    last_timestamp = None
    for index, memory in enumerate(raw_memories):
        if not isinstance(memory, Mapping):
            raise InferenceViewError(f"memory_bank[{index}] must be an object")
        where = f"memory_bank[{index}]"
        memory_id = _required_text(memory, "memory_id", where)
        if memory_id in memory_ids:
            raise InferenceViewError(f"duplicate memory_id: {memory_id}")
        timestamp = _required_int(memory, "timestamp", where)
        if last_timestamp is not None and timestamp < last_timestamp:
            raise InferenceViewError("memory_bank must be chronological")
        memory_ids.add(memory_id)
        last_timestamp = timestamp
        memories.append(
            {
                "memory_id": memory_id,
                "content": _required_text(memory, "content", where),
                "timestamp": timestamp,
                "source_session_id": _optional_text(memory, "source_session_id", where),
            }
        )

    view = {
        "schema_version": SCHEMA_VERSION,
        "example_id": example_id,
        "task_family": task_family,
        "past_sessions": sessions,
        "current_task": current_task,
        "memory_bank": memories,
    }
    assert_blind_view(view)
    return view


def assert_blind_view(view: Mapping[str, Any]) -> None:
    """Fail if evaluator-only fields reappear in an inference view."""
    if FORBIDDEN_TOP_LEVEL.intersection(view):
        raise InferenceViewError("evaluation-only top-level field leaked into inference view")
    memories = view.get("memory_bank")
    if not isinstance(memories, list):
        raise InferenceViewError("inference view lacks memory_bank")
    for memory in memories:
        if not isinstance(memory, Mapping):
            raise InferenceViewError("inference memory must be an object")
        leaked = FORBIDDEN_MEMORY_FIELDS.intersection(memory)
        if leaked:
            raise InferenceViewError(f"evaluation-only memory fields leaked: {sorted(leaked)}")


def canonical_sha256(view: Mapping[str, Any]) -> str:
    assert_blind_view(view)
    payload = json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

