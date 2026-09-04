#!/usr/bin/env python3
"""Pure request builder for the matched Mem-Gallery answer model."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


ANSWER_MODEL = "Qwen3-VL-8B-Instruct"
ANSWER_TEMPERATURE = 0.0
ANSWER_MAX_OUTPUT_TOKENS = 128

SYSTEM_PROMPT = """You are an AI assistant evaluated on multimodal long-term conversational memory.
For the given question-answering task, your responses must be concise, yet complete enough to accurately answer the questions.
If multiple pieces of information about the same event appear in the conversation, always rely on the most recent information.

The question-answering evaluation will contain several multimodal task types:

Factual Retrieval: Retrieve explicit facts mentioned in the conversation for the answer.
Multi-entity Reasoning: Combine the retrieved information to reason and infer an answer.

Temporal Reasoning: Resolve time-dependent questions.

Visual-centric Reasoning: Besides textual information, answer questions using visual images in the conversation.

Test-time Learning: Learn new visual knowledge from provided images within historical dialogue and use it in question-answering.

Visual-centric Search: Find the image(s) that match the information in a given query and return their image ID(s).
Conflict Detection: Detect contradictions between the conversation history and the information provided in the question.

Knowledge Resolution: Resolve knowledge conflicts or updates by prioritizing the most recent information.

Answer Refusal: Decline to answer when the information does not exist in the conversation history.
Follow all instructions strictly. Only answer using information contained within the multimodal conversation. Do not hallucinate. Always remain consistent and grounded in the dialogue history."""

CATEGORY_CONSTRAINTS = {
    "AR": "Provide your answer based on the information in the conversation. Only if the information about the question is not present in the conversation, reply with: “Not mentioned.”",
    "CD": "Please check whether this information conflicts with the conversation, and reply strictly with either “Yes.” or “No.”",
    "VS": "Return the image_id of the image(s). If there are multiple images, sort them in ascending order and separate them by commas. Format example: “D2:IMG_003, D2:IMG_010, D10:IMG_002” (for format reference only).",
}
MEMORY_HEADER = "The retrieved memory contents are as follows:\n\n"
QUESTION_IMAGE_MARKER = "Here is the attached image of the question:"


def _query_prompt(query: Mapping[str, Any]) -> str:
    question = query.get("question")
    speaker_a = query.get("speaker_a")
    speaker_b = query.get("speaker_b")
    category = query.get("category", "")
    if not all(isinstance(value, str) and value for value in (question, speaker_a, speaker_b)):
        raise ValueError("question and speaker identities must be nonempty strings")
    if not isinstance(category, str):
        raise ValueError("category must be a string")
    constraint = CATEGORY_CONSTRAINTS.get(category.upper()) if category else None
    suffix = f"\n\n{constraint}" if constraint else ""
    return (
        f"Your task is to answer the question about the conversation between {speaker_a} and {speaker_b} "
        "in a concise manner with the help of memory content.\n"
        "Please only provide the content of the answer, without including introductory phrases like 'answer:'.\n"
        "For questions that require answering a date or time, strictly follow the format and provide a specific date or time whenever possible.\n"
        "Generate answers primarily concise, yet complete enough to accurately answer the questions.\n"
        f"The current question is as follows:\n{question} {suffix}"
    )


def _validate_no_answer_leak(query: Mapping[str, Any]) -> None:
    prohibited = {"answer", "gold", "reference_answer", "original_answer"}
    leaked = prohibited.intersection(query)
    if leaked:
        raise ValueError(f"raw answer field leaked into answer request: {sorted(leaked)}")


def build_answer_request(
    evidence: Sequence[Mapping[str, Any]],
    query: Mapping[str, Any],
    *,
    multimodal_memory: bool,
    seed: int,
) -> dict[str, Any]:
    """Build an image-reference request before byte encoding and transport."""
    _validate_no_answer_leak(query)
    if seed not in {0, 1, 2}:
        raise ValueError("seed must be one of the frozen matched seeds")
    content: list[dict[str, Any]] = [{"type": "text", "text": MEMORY_HEADER}]
    if multimodal_memory:
        for record in evidence:
            text = record.get("multimodal_text")
            images = record.get("image_ids", [])
            source_image_id = record.get("source_image_id") or ""
            if not isinstance(text, str):
                raise ValueError("multimodal evidence requires multimodal_text")
            if not isinstance(images, list) or len(images) > 1:
                raise ValueError("official Mem-Gallery evidence permits at most one image per round")
            if images:
                content.append(
                    {
                        "type": "text",
                        "text": f"{text}\nimage:\nimage_id: {source_image_id}\nimage_content:",
                    }
                )
                content.append({"type": "image_ref", "image_id": images[0]})
            else:
                content.append({"type": "text", "text": text})
    else:
        joined: list[str] = []
        for record in evidence:
            text = record.get("text")
            if not isinstance(text, str):
                raise ValueError("textual evidence requires text")
            joined.append(text)
        if joined:
            content.append({"type": "text", "text": "\n".join(joined)})

    content.append({"type": "text", "text": _query_prompt(query)})
    question_image = query.get("question_image_id")
    if question_image is not None:
        if not isinstance(question_image, str) or not question_image:
            raise ValueError("question_image_id must be a nonempty string or null")
        content.append({"type": "text", "text": QUESTION_IMAGE_MARKER})
        content.append({"type": "image_ref", "image_id": question_image})
    return {
        "model": ANSWER_MODEL,
        "temperature": ANSWER_TEMPERATURE,
        "max_tokens": ANSWER_MAX_OUTPUT_TOKENS,
        "seed": seed,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    }

