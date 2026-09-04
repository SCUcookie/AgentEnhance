#!/usr/bin/env python3
"""Source-faithful, answer-isolating adapter for Mem-Gallery controls."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence


def canonical_json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_relative(raw: str, label: str) -> PurePosixPath:
    path = PurePosixPath(raw)
    if (
        not raw
        or "\\" in raw
        or "\x00" in raw
        or path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or any(not part for part in path.parts)
    ):
        raise ValueError(f"unsafe {label}: {raw!r}")
    return path


def resolve_image_reference(raw: str, kind: str) -> str:
    """Mirror the accepted dataset audit and official runner path semantics."""
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise ValueError(f"invalid {kind} image reference: {raw!r}")
    if raw.startswith("../image/"):
        suffix = raw[len("../image/") :]
        relative = PurePosixPath("data/image") / _safe_relative(suffix, f"{kind} image")
    elif kind == "conversation":
        relative = PurePosixPath("data") / _safe_relative(raw, f"{kind} image")
    elif kind == "question":
        relative = PurePosixPath("data/image") / _safe_relative(raw, f"{kind} image")
    else:
        raise ValueError(f"unknown image-reference kind: {kind}")
    if relative.parts[:2] != ("data", "image"):
        raise ValueError(f"{kind} image escapes data/image: {raw!r}")
    return relative.as_posix()


def _optional_string_list(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return value


def _first(items: Sequence[str]) -> str:
    return items[0] if items else ""


def adapt_scenario(payload: Mapping[str, Any], scenario: str) -> dict[str, Any]:
    """Project one authority JSON into memory records and answer-free queries.

    The function reads gold answers only to bind their hashes and the canonical QA
    identity.  Raw answers are never returned in the query projection.
    """
    if not isinstance(scenario, str) or not scenario:
        raise ValueError("scenario must be a nonempty string")
    profile = payload.get("character_profile", {})
    if not isinstance(profile, Mapping):
        raise ValueError("character_profile must be an object")
    name = profile.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError("character_profile.name must be a string")
    speaker_a = f"user ({name})" if name else "user"
    speaker_b = "assistant"
    sessions = payload.get("multi_session_dialogues")
    qas = payload.get("human-annotated QAs")
    if not isinstance(sessions, list) or not isinstance(qas, list):
        raise ValueError("dialogues and QAs must be lists")

    records: list[dict[str, Any]] = []
    for session_index, session in enumerate(sessions):
        if not isinstance(session, Mapping):
            raise ValueError(f"session {session_index} must be an object")
        dialogues = session.get("dialogues")
        if not isinstance(dialogues, list):
            raise ValueError(f"session {session_index} dialogues must be a list")
        session_id = session.get("session_id", "")
        session_date = session.get("date", "")
        if not isinstance(session_date, str):
            raise ValueError(f"session {session_index} date must be a string")
        for round_index, dialogue in enumerate(dialogues):
            if not isinstance(dialogue, Mapping):
                raise ValueError(f"session {session_index} round {round_index} must be an object")
            user = dialogue.get("user", "")
            assistant = dialogue.get("assistant", "")
            if not isinstance(user, str) or not isinstance(assistant, str):
                raise ValueError("dialogue user and assistant must be strings")
            if not user and not assistant:
                continue
            parts: list[str] = []
            if user:
                parts.append(f"{speaker_a}: {user}")
            if assistant:
                parts.append(f"{speaker_b}: {assistant}")
            raw_text = "\n".join(parts)

            images = _optional_string_list(dialogue.get("input_image"), "input_image")
            captions = _optional_string_list(dialogue.get("image_caption"), "image_caption")
            source_image_ids = _optional_string_list(dialogue.get("image_id"), "image_id")
            image_paths = [resolve_image_reference(images[0], "conversation")] if images else []
            caption = _first(captions)
            source_image_id = _first(source_image_ids)
            captioned_text = raw_text
            if image_paths and (source_image_id or caption):
                captioned_text += (
                    "\nimage:\nimage_id: " + source_image_id + "\nimage_caption: " + caption
                )
            records.append(
                {
                    "memory_id": f"{scenario}:session-{session_index}:round-{round_index}",
                    "chronological_index": len(records),
                    "text": captioned_text,
                    "multimodal_text": raw_text,
                    "image_ids": image_paths,
                    "source_image_id": source_image_id or None,
                    "image_caption": caption or None,
                    "session_index": session_index,
                    "round_index": round_index,
                    "session_id": session_id,
                    "timestamp": session_date,
                    "source_dialogue_id": dialogue.get("round", ""),
                }
            )

    queries: list[dict[str, Any]] = []
    for qa_index, qa in enumerate(qas):
        if not isinstance(qa, Mapping):
            raise ValueError(f"QA {qa_index} must be an object")
        question = qa.get("question")
        answer = qa.get("answer")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"QA {qa_index} question must be nonempty")
        if not isinstance(answer, str):
            raise ValueError(f"QA {qa_index} answer must be a string")
        question_image = qa.get("question_image")
        if question_image is not None and not isinstance(question_image, str):
            raise ValueError(f"QA {qa_index} question_image must be a string")
        question_image_id = (
            resolve_image_reference(question_image, "question") if question_image else None
        )
        image_caption = qa.get("image_caption")
        if image_caption is not None and not isinstance(image_caption, str):
            raise ValueError(f"QA {qa_index} image_caption must be a string")
        retrieval_query = question
        if question_image_id and image_caption:
            retrieval_query += "\nquestion's image:\nimage_caption: " + image_caption
        qid = f"{scenario}:{qa_index}"
        queries.append(
            {
                "qid": qid,
                "scenario": scenario,
                "qa_index": qa_index,
                "question": question,
                "retrieval_query_text": retrieval_query,
                "question_image_id": question_image_id,
                "question_image_caption": image_caption or None,
                "category": qa.get("point", ""),
                "session_id": qa.get("session_id", ""),
                "speaker_a": speaker_a,
                "speaker_b": speaker_b,
                "answer_sha256": sha256_bytes(answer.encode("utf-8")),
                "question_sha256": sha256_bytes(question.encode("utf-8")),
                "qa_canonical_sha256": sha256_bytes(canonical_json_bytes(dict(qa))),
            }
        )
    return {
        "scenario": scenario,
        "speaker_a": speaker_a,
        "speaker_b": speaker_b,
        "memory_records": records,
        "queries": queries,
    }


def validate_query_projection(
    adapted_queries: Sequence[Mapping[str, Any]],
    frozen_question_rows: Sequence[Mapping[str, Any]],
) -> None:
    """Bind an answer-free projection to accepted question-index identities."""
    if len(adapted_queries) != len(frozen_question_rows):
        raise ValueError("query projection denominator differs from frozen question index")
    identity_fields = (
        "qid",
        "scenario",
        "qa_index",
        "question_sha256",
        "answer_sha256",
        "qa_canonical_sha256",
    )
    for position, (query, frozen) in enumerate(zip(adapted_queries, frozen_question_rows)):
        for field in identity_fields:
            if query.get(field) != frozen.get(field):
                raise ValueError(f"query projection identity drift at {position}: {field}")
        if "answer" in query:
            raise ValueError(f"raw answer leaked into query projection at {position}")

