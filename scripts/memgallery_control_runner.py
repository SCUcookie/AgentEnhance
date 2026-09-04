#!/usr/bin/env python3
"""Composable, result-free runner core for the seven Mem-Gallery controls."""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Mapping, Sequence

from memgallery_answer_contract import build_answer_request
from memgallery_control_core import CONTROL_METHODS, pack_evidence, retrieve_control


DENSE_METHODS = {"naive-rag", "hybrid-rag"}
MULTIMODAL_METHODS = {"full-memory-mm"}
FULL_MEMORY_METHODS = {"full-memory-text", "full-memory-mm"}


def _finite_duration(started: float, finished: float, label: str) -> float:
    duration = float(finished - started)
    if not math.isfinite(duration) or duration < 0:
        raise ValueError(f"{label} clock duration is invalid")
    return duration


def _packing_records(
    records: Sequence[Mapping[str, Any]], method_id: str
) -> tuple[list[Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    originals = {str(record["memory_id"]): record for record in records}
    if method_id not in MULTIMODAL_METHODS:
        return list(records), originals
    projected: list[dict[str, Any]] = []
    for record in records:
        text = record.get("multimodal_text")
        images = record.get("image_ids", [])
        source_image_id = record.get("source_image_id") or ""
        if not isinstance(text, str) or not isinstance(images, list) or len(images) > 1:
            raise ValueError("invalid multimodal record for evidence packing")
        prompt_text = text
        if images:
            prompt_text += f"\nimage:\nimage_id: {source_image_id}\nimage_content:"
        projected.append(
            {
                "memory_id": record["memory_id"],
                "chronological_index": record["chronological_index"],
                "text": prompt_text,
                "image_ids": images,
            }
        )
    return projected, originals


def _failure_call_record(exc: Exception, elapsed: float) -> dict[str, Any]:
    attached = getattr(exc, "record", None)
    if isinstance(attached, Mapping):
        return dict(attached)
    return {
        "schema_version": "agentenhance.memgallery_endpoint_call.v1",
        "call_category": "final_answer",
        "status": "FAILED",
        "attempts": 1,
        "retry_count": 0,
        "wall_seconds": elapsed,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "error_type": type(exc).__name__,
        "error": str(exc),
    }


def run_control_scenario(
    method_id: str,
    scenario_projection: Mapping[str, Any],
    *,
    seed: int,
    token_count: Callable[[str], int],
    answer_call: Callable[[Mapping[str, Any]], tuple[str, Mapping[str, Any]]],
    dense_document_vectors: Sequence[Sequence[float]] | None = None,
    dense_query_vector: Callable[[Mapping[str, Any]], Sequence[float]] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run one already-adapted scenario without scoring or filesystem mutation."""
    if method_id not in CONTROL_METHODS:
        raise ValueError(f"unregistered control method: {method_id}")
    if seed not in {0, 1, 2}:
        raise ValueError("seed must be one of 0, 1, or 2")
    records = scenario_projection.get("memory_records")
    queries = scenario_projection.get("queries")
    scenario = scenario_projection.get("scenario")
    if not isinstance(records, list) or not isinstance(queries, list) or not isinstance(scenario, str):
        raise ValueError("scenario projection shape is invalid")
    if method_id in DENSE_METHODS:
        if dense_document_vectors is None or dense_query_vector is None:
            raise ValueError(f"{method_id} requires frozen document and query embeddings")
        if len(dense_document_vectors) != len(records):
            raise ValueError("dense document vector count differs from memory records")
    elif dense_document_vectors is not None or dense_query_vector is not None:
        raise ValueError(f"{method_id} must not receive an unused dense provider")

    predictions: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    retrieval_traces: list[dict[str, Any]] = []
    for query in queries:
        qid = query.get("qid") if isinstance(query, Mapping) else None
        if not isinstance(qid, str) or not qid:
            raise ValueError("query qid must be a nonempty string")
        question_started = clock()
        retrieved_ids: list[str] = []
        retrieval_seconds = 0.0
        answer_seconds = 0.0
        failure_stage = None
        stage = "retrieval"
        answer_attempted = False
        try:
            retrieval_started = clock()
            query_vector = dense_query_vector(query) if dense_query_vector is not None else None
            ranked = retrieve_control(
                method_id,
                records,
                str(query.get("retrieval_query_text", query.get("question", ""))),
                top_k=10,
                dense_document_vectors=dense_document_vectors,
                dense_query_vector=query_vector,
            )
            packing_candidates, originals = _packing_records(ranked, method_id)
            packed, budget = pack_evidence(
                packing_candidates,
                token_count,
                token_image_budget=4096,
                image_token_cost=256,
                max_images=20 if method_id == "full-memory-mm" else None,
                newest_preserving=method_id in FULL_MEMORY_METHODS,
            )
            selected = [originals[str(record["memory_id"])] for record in packed]
            retrieved_ids = [str(record["memory_id"]) for record in selected]
            retrieval_seconds = _finite_duration(retrieval_started, clock(), "retrieval")
            stage = "request_build"
            request = build_answer_request(
                selected,
                query,
                multimodal_memory=method_id in MULTIMODAL_METHODS,
                seed=seed,
            )
            stage = "answer"
            answer_started = clock()
            answer_attempted = True
            prediction, call_record = answer_call(request)
            answer_seconds = _finite_duration(answer_started, clock(), "answer")
            if not isinstance(prediction, str) or not prediction.strip():
                raise ValueError("answer_call returned an empty prediction")
            call = dict(call_record)
            if call.get("status") != "ACCEPTED" or call.get("call_category") != "final_answer":
                raise ValueError("answer_call acceptance record is invalid")
            call.update({"qid": qid, "method_id": method_id, "seed": seed})
            calls.append(call)
            status = "ACCEPTED"
            error_type = None
            error = None
        except Exception as exc:
            prediction = ""
            status = "FAILED"
            error_type = type(exc).__name__
            error = str(exc)
            failure_stage = stage
            if answer_attempted:
                answer_seconds = _finite_duration(answer_started, clock(), "failed answer")
                failure_call = _failure_call_record(exc, answer_seconds)
                failure_call.update({"qid": qid, "method_id": method_id, "seed": seed})
                calls.append(failure_call)
            budget = {
                "text_tokens": 0,
                "images": 0,
                "image_token_cost": 0,
                "total_budget_units": 0,
            }
        latency = _finite_duration(question_started, clock(), "question")
        predictions.append(
            {
                "schema_version": "agentenhance.memgallery_prediction.v1",
                "method_id": method_id,
                "seed": seed,
                "qid": qid,
                "status": status,
                "prediction": prediction,
                "error_type": error_type,
                "error": error,
                "retrieved_memory_ids": retrieved_ids,
                "retrieval_count": len(retrieved_ids),
                "latency_seconds": latency,
            }
        )
        retrieval_traces.append(
            {
                "qid": qid,
                "method_id": method_id,
                "seed": seed,
                "status": status,
                "retrieved_memory_ids": retrieved_ids,
                "retrieval_count": len(retrieved_ids),
                "budget": budget,
                "retrieval_seconds": retrieval_seconds,
                "answer_seconds": answer_seconds,
                "failure_stage": failure_stage,
            }
        )
        if "answer_started" in locals():
            del answer_started
    return {
        "schema_version": "agentenhance.memgallery_control_scenario_result.v1",
        "status": "TERMINAL_SCENARIO_COMPLETE",
        "scenario": scenario,
        "method_id": method_id,
        "seed": seed,
        "questions": len(queries),
        "accepted_questions": sum(row["status"] == "ACCEPTED" for row in predictions),
        "failed_questions": sum(row["status"] == "FAILED" for row in predictions),
        "predictions": predictions,
        "retrieval_traces": retrieval_traces,
        "call_records": calls,
        "scores_observed": 0,
    }
