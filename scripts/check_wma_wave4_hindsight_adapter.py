#!/usr/bin/env python3
"""Run the frozen persistence lifecycle gate for the Hindsight WMA adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


EARLIEST_FACT = "blue-orchid-739"
QUERY = "What is the private project code from the earliest session?"
IMAGE_ID = "eb_alfred_base_01_img_001"
CAPTION = (
    "A top-down wooden desk scene with a lit lamp, chairs, a gray bowl, a CD, "
    "and a small rectangular object."
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_execution_source(source_root: Path, record_path: Path) -> dict[str, Any]:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record.get("status") != "TERMINAL_ACCEPTED":
        raise RuntimeError("Hindsight execution-source record is not accepted")
    if record.get("source_revision") != "5e71494702bc050b6d58e783e6761f6c6cf3b74b":
        raise RuntimeError("Hindsight execution-source revision mismatch")
    expected = {
        str(row["path"]): (int(row["bytes"]), str(row["sha256"]))
        for row in record.get("files", [])
    }
    observed: dict[str, tuple[int, str]] = {}
    for path in sorted(source_root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"symlink in Hindsight execution source: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(source_root).as_posix()
        observed[relative] = (path.stat().st_size, sha256_file(path))
    if observed != expected:
        raise RuntimeError("Hindsight execution source no longer matches its accepted record")
    if len(observed) != 563 or sum(size for size, _digest in observed.values()) != 9_417_481:
        raise RuntimeError("Hindsight execution-source cardinality mismatch")
    return {
        "revision": record["source_revision"],
        "regular_files": len(observed),
        "total_bytes": sum(size for size, _digest in observed.values()),
    }


def build_turns(image_path: Path, image_id: str = IMAGE_ID) -> list[tuple[str, list[Any]]]:
    from eval_framework.datasets.schemas import Attachment, NormalizedTurn

    sessions = []
    for session_index in range(3):
        session_id = f"wave4-hindsight-lifecycle-s{session_index + 1:02d}"
        turns = []
        for pair_index in range(4):
            turn_index = pair_index * 2
            if session_index == 0 and pair_index == 0:
                user_text = (
                    f"Remember that the private project code is {EARLIEST_FACT}. "
                    "This fact belongs to the earliest lifecycle session."
                )
                attachments = (
                    Attachment(
                        caption=CAPTION,
                        type="image_caption",
                        image_id=image_id,
                        file_path=str(image_path),
                    ),
                )
            else:
                user_text = (
                    f"Session {session_index + 1}, note {pair_index + 1}: "
                    f"the verification token is token-{session_index + 1}-{pair_index + 1}."
                )
                attachments = ()
            turns.extend(
                [
                    NormalizedTurn(
                        sample_id="wave4-hindsight-lifecycle-sample",
                        session_id=session_id,
                        turn_index=turn_index,
                        role="user",
                        text=user_text,
                        attachments=attachments,
                        timestamp=f"2026-09-04T00:{session_index}{pair_index}:00Z",
                    ),
                    NormalizedTurn(
                        sample_id="wave4-hindsight-lifecycle-sample",
                        session_id=session_id,
                        turn_index=turn_index + 1,
                        role="assistant",
                        text=f"Acknowledged lifecycle note {session_index + 1}-{pair_index + 1}.",
                        timestamp=f"2026-09-04T00:{session_index}{pair_index}:01Z",
                    ),
                ]
            )
        sessions.append((session_id, turns))
    return sessions


def compact_retrieval(record: Any) -> list[dict[str, Any]]:
    return [
        {
            "rank": int(item.rank),
            "memory_id": str(item.memory_id),
            "score": float(item.score),
            "text": str(item.text),
            "image_path": item.image_path,
        }
        for item in record.items
    ]


def lifecycle_invariants(
    *,
    capabilities: dict[str, Any],
    snapshot_before: list[Any],
    snapshot_after: list[Any],
    delta: list[Any],
    retrieval_before: Any,
    retrieval_after: Any,
    image_id: str,
    pg0_root: Path,
) -> dict[str, bool]:
    before_ids = {str(row.memory_id) for row in snapshot_before}
    after_ids = {str(row.memory_id) for row in snapshot_after}
    delta_ids = {str(row.raw_backend_id) for row in delta}
    retrieval_items = list(retrieval_before.items) + list(retrieval_after.items)
    retrieval_text = "\n".join(str(item.text) for item in retrieval_items)
    provenance = "\n".join(
        str(row.text) + json.dumps(row.metadata, sort_keys=True, default=str)
        for row in snapshot_after
    )
    traces = (retrieval_before.raw_trace, retrieval_after.raw_trace)
    return {
        "registered_factory": True,
        "caption_mediated_declared": capabilities.get("caption_mediated") is True,
        "native_multimodal_false": capabilities.get("native_multimodal") is False,
        "reflect_excluded": capabilities.get("reflect_excluded") is True,
        "snapshot_before_nonempty": bool(snapshot_before),
        "snapshot_ids_stable_after_reload": bool(before_ids) and before_ids == after_ids,
        "delta_matches_snapshot": delta_ids == before_ids,
        "retrieval_before_nonempty": bool(retrieval_before.items),
        "retrieval_after_nonempty": bool(retrieval_after.items),
        "retrieval_scores_finite": all(
            math.isfinite(float(item.score)) for item in retrieval_items
        ),
        "earliest_fact_retrieved_before_and_after": all(
            any(EARLIEST_FACT in str(item.text) for item in record.items)
            for record in (retrieval_before, retrieval_after)
        ),
        "earliest_fact_present_in_combined_retrieval": EARLIEST_FACT in retrieval_text,
        "image_provenance_retained": image_id in provenance,
        "no_native_image_retrieval_claim": all(
            item.image_path is None for item in retrieval_items
        ),
        "official_final_scores_exposed": all(
            len(trace.get("official_scores", [])) == len(record.items)
            and all("final" in scores for scores in trace.get("official_scores", []))
            for record, trace in zip((retrieval_before, retrieval_after), traces)
        ),
        "three_sync_retain_calls": all(
            trace.get("internal_retain_calls") == 3 for trace in traces
        ),
        "reflect_never_called": all(trace.get("reflect_called") is False for trace in traces),
        "pg0_persistence_root_exists": pg0_root.is_dir()
        and any(path.is_file() for path in pg0_root.rglob("*")),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--execution-source-record", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--embedding-model-path", type=Path, required=True)
    parser.add_argument("--reranker-model-path", type=Path, required=True)
    parser.add_argument("--image-path", type=Path, required=True)
    parser.add_argument("--image-sha256", required=True)
    parser.add_argument("--image-id", default=IMAGE_ID)
    args = parser.parse_args()

    image_path = args.image_path.resolve()
    if not image_path.is_file() or sha256_file(image_path) != args.image_sha256:
        raise SystemExit("fixed lifecycle image is missing or has the wrong digest")
    storage_root = args.storage_root.resolve()
    if storage_root.exists():
        raise SystemExit(f"refusing existing lifecycle storage root: {storage_root}")
    storage_root.mkdir(parents=True)
    source_root = args.source_root.resolve()
    source_evidence = validate_execution_source(
        source_root, args.execution_source_record.resolve()
    )

    from eval_framework.memory_adapters import registry

    baseline = "Hindsight"
    if baseline not in registry.EXTERNAL_ADAPTER_KEYS:
        raise SystemExit("Wave-4 runtime registration missing for Hindsight")
    adapter = registry.create_external_adapter(
        baseline,
        config_overrides={
            "source_root": str(source_root),
            "storage_root": str(storage_root),
            "embedding_model_path": str(args.embedding_model_path.resolve()),
            "reranker_model_path": str(args.reranker_model_path.resolve()),
        },
    )
    try:
        capabilities = adapter.get_capabilities()
        adapter.reset()
        sessions = build_turns(image_path, args.image_id)
        for session_id, turns in sessions:
            for turn in turns:
                adapter.ingest_turn(turn)
            adapter.end_session(session_id)

        snapshot_before = adapter.snapshot_memories()
        delta = adapter.export_memory_delta(sessions[-1][0])
        retrieval_before = adapter.retrieve(QUERY, top_k=10)
        adapter.reload_from_disk()
        snapshot_after = adapter.snapshot_memories()
        retrieval_after = adapter.retrieve(QUERY, top_k=10)
    finally:
        adapter.close()

    pg0_root = storage_root / ".pg0" / "instances" / "agentenhance-hindsight-g000"
    invariants = lifecycle_invariants(
        capabilities=capabilities,
        snapshot_before=snapshot_before,
        snapshot_after=snapshot_after,
        delta=delta,
        retrieval_before=retrieval_before,
        retrieval_after=retrieval_after,
        image_id=args.image_id,
        pg0_root=pg0_root,
    )
    payload = {
        "schema_version": "agentenhance.wma_wave4_hindsight_lifecycle.v1",
        "status": "LIFECYCLE_PASSED" if all(invariants.values()) else "LIFECYCLE_REJECTED",
        "baseline": baseline,
        "adapter_class": type(adapter).__name__,
        "capabilities": capabilities,
        "execution_source": source_evidence,
        "fixed_image": {
            "image_id": args.image_id,
            "sha256": args.image_sha256,
            "caption_mediated_only": True,
        },
        "counts": {
            "sessions": len(sessions),
            "turns": sum(len(turns) for _session_id, turns in sessions),
            "user_assistant_pairs": 12,
            "snapshot_before": len(snapshot_before),
            "snapshot_after": len(snapshot_after),
            "delta": len(delta),
            "retrieval_before": len(retrieval_before.items),
            "retrieval_after": len(retrieval_after.items),
        },
        "pg0": {
            "relative_root": ".pg0/instances/agentenhance-hindsight-g000",
            "regular_files_after_clean_shutdown": sum(
                path.is_file() for path in pg0_root.rglob("*")
            ),
        },
        "invariants": invariants,
        "retrieval_before": compact_retrieval(retrieval_before),
        "retrieval_after": compact_retrieval(retrieval_after),
        "raw_trace_before": retrieval_before.raw_trace,
        "raw_trace_after": retrieval_after.raw_trace,
    }
    print(
        "AGENTENHANCE_WAVE4_HINDSIGHT_LIFECYCLE="
        + json.dumps(payload, sort_keys=True, default=str, allow_nan=False)
    )
    return 0 if payload["status"] == "LIFECYCLE_PASSED" else 4


if __name__ == "__main__":
    raise SystemExit(main())
