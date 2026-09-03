#!/usr/bin/env python3
"""Run a persistence-aware lifecycle gate for one Wave-3 memory adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_turns(image_path: Path, image_sha256: str, image_id: str) -> list[tuple[str, list[Any]]]:
    from eval_framework.datasets.schemas import Attachment, NormalizedTurn

    sessions = []
    for session_index in range(3):
        session_id = f"wave3-lifecycle-s{session_index + 1:02d}"
        turns = []
        for pair_index in range(4):
            turn_base = pair_index * 2
            if session_index == 0 and pair_index == 0:
                user_text = (
                    "Remember that the private project code is blue-orchid-739. "
                    "This fact belongs to the earliest lifecycle session."
                )
                attachments = (
                    Attachment(
                        caption=(
                            "A top-down wooden desk scene with a lit lamp, chairs, "
                            "a gray bowl, a CD, and a small rectangular object."
                        ),
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
            turns.append(
                NormalizedTurn(
                    sample_id="wave3-lifecycle-sample",
                    session_id=session_id,
                    turn_index=turn_base,
                    role="user",
                    text=user_text,
                    attachments=attachments,
                    timestamp=f"2026-09-04T00:{session_index}{pair_index}:00Z",
                )
            )
            turns.append(
                NormalizedTurn(
                    sample_id="wave3-lifecycle-sample",
                    session_id=session_id,
                    turn_index=turn_base + 1,
                    role="assistant",
                    text=f"Acknowledged lifecycle note {session_index + 1}-{pair_index + 1}.",
                    timestamp=f"2026-09-04T00:{session_index}{pair_index}:01Z",
                )
            )
        sessions.append((session_id, turns))
    return sessions


def compact_retrieval(record: Any) -> list[dict[str, Any]]:
    return [
        {
            "rank": int(item.rank),
            "memory_id": str(item.memory_id),
            "score": float(item.score),
            "text_nonempty": bool(str(item.text).strip()),
            "image_path": item.image_path,
        }
        for item in record.items
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", choices=("MemoryOS", "MemGAS"), required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--embedding-model-path", type=Path, required=True)
    parser.add_argument("--image-path", type=Path, required=True)
    parser.add_argument("--image-sha256", required=True)
    parser.add_argument("--image-id", default="eb_alfred_base_01_img_001")
    args = parser.parse_args()

    image_path = args.image_path.resolve()
    if not image_path.is_file() or sha256_file(image_path) != args.image_sha256:
        raise SystemExit("fixed lifecycle image is missing or has the wrong digest")
    storage_root = args.storage_root.resolve()
    if storage_root.exists():
        raise SystemExit(f"refusing existing lifecycle storage root: {storage_root}")
    storage_root.mkdir(parents=True)

    from eval_framework.memory_adapters import registry

    if args.baseline not in registry.EXTERNAL_ADAPTER_KEYS:
        raise SystemExit(f"Wave-3 runtime registration missing for {args.baseline}")
    adapter = registry.create_external_adapter(
        args.baseline,
        config_overrides={
            "source_root": str(args.source_root.resolve()),
            "storage_root": str(storage_root),
            "embedding_model_path": str(args.embedding_model_path.resolve()),
        },
    )
    capabilities = adapter.get_capabilities()
    adapter.reset()
    sessions = build_turns(image_path, args.image_sha256, args.image_id)
    for session_id, turns in sessions:
        for turn in turns:
            adapter.ingest_turn(turn)
        adapter.end_session(session_id)

    snapshot_before = adapter.snapshot_memories()
    retrieval_before = adapter.retrieve(
        "What is the private project code from the earliest session?", top_k=10
    )
    if not hasattr(adapter, "reload_from_disk"):
        raise RuntimeError("Wave-3 adapter lacks the frozen reload_from_disk lifecycle hook")
    adapter.reload_from_disk()
    snapshot_after = adapter.snapshot_memories()
    retrieval_after = adapter.retrieve(
        "What is the private project code from the earliest session?", top_k=10
    )

    before_ids = {str(row.memory_id) for row in snapshot_before}
    after_ids = {str(row.memory_id) for row in snapshot_after}
    all_retrieval_items = list(retrieval_before.items) + list(retrieval_after.items)
    invariants = {
        "registered_factory": True,
        "caption_mediated_declared": capabilities.get("caption_mediated") is True,
        "native_multimodal_false": capabilities.get("native_multimodal") is False,
        "snapshot_before_nonempty": bool(snapshot_before),
        "snapshot_ids_stable_after_reload": before_ids == after_ids,
        "retrieval_before_nonempty": bool(retrieval_before.items),
        "retrieval_after_nonempty": bool(retrieval_after.items),
        "retrieval_scores_finite": all(
            math.isfinite(float(item.score)) for item in all_retrieval_items
        ),
        "earliest_fact_retrieved_before": any(
            "blue-orchid-739" in str(item.text) for item in retrieval_before.items
        ),
        "earliest_fact_retrieved_after": any(
            "blue-orchid-739" in str(item.text) for item in retrieval_after.items
        ),
        "image_provenance_retained": any(
            args.image_id in str(row.text)
            or args.image_id in json.dumps(row.metadata, sort_keys=True, default=str)
            for row in snapshot_after
        ),
        "no_native_image_retrieval_claim": all(
            item.image_path is None for item in all_retrieval_items
        ),
    }
    method_evidence: dict[str, Any]
    if args.baseline == "MemoryOS":
        json_files = sorted(storage_root.rglob("*.json"))
        parsed_files = 0
        for path in json_files:
            json.loads(path.read_text(encoding="utf-8"))
            parsed_files += 1
        layers = {str(row.metadata.get("layer")) for row in snapshot_after}
        method_evidence = {
            "json_files": parsed_files,
            "snapshot_layers": sorted(layers),
            "short_term_count": len(adapter._backend.short_term_memory.get_all()),
            "mid_term_session_count": len(adapter._backend.mid_term_memory.sessions),
        }
        invariants.update(
            {
                "all_persistence_json_parseable": parsed_files >= 2,
                "short_term_capacity_crossed": method_evidence["short_term_count"] == 10,
                "mid_term_migration_observed": method_evidence["mid_term_session_count"] > 0,
                "retrieval_error_overlay_clean": retrieval_before.raw_trace.get(
                    "swallowed_error_detected"
                )
                is False
                and retrieval_after.raw_trace.get("swallowed_error_detected") is False,
            }
        )
    else:
        state_files = sorted(storage_root.rglob("memory_state.pt"))
        method_evidence = {
            "memory_state_files": len(state_files),
            "backend_records": len(adapter._backend.store.records),
            "gmm_fallback_count_before": retrieval_before.raw_trace.get(
                "gmm_fallback_count_total"
            ),
            "gmm_fallback_count_after": retrieval_after.raw_trace.get(
                "gmm_fallback_count_total"
            ),
        }
        invariants.update(
            {
                "three_session_records_observed": method_evidence["backend_records"] == 3,
                "memory_state_persisted": method_evidence["memory_state_files"] == 1,
                "gmm_fallback_counter_exposed": isinstance(
                    method_evidence["gmm_fallback_count_before"], int
                )
                and isinstance(method_evidence["gmm_fallback_count_after"], int),
            }
        )

    payload = {
        "schema_version": "agentenhance.wma_wave3_adapter_lifecycle.v1",
        "status": "LIFECYCLE_PASSED" if all(invariants.values()) else "LIFECYCLE_REJECTED",
        "baseline": args.baseline,
        "adapter_class": type(adapter).__name__,
        "capabilities": capabilities,
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
            "retrieval_before": len(retrieval_before.items),
            "retrieval_after": len(retrieval_after.items),
        },
        "method_evidence": method_evidence,
        "invariants": invariants,
        "retrieval_before": compact_retrieval(retrieval_before),
        "retrieval_after": compact_retrieval(retrieval_after),
        "raw_trace_before": retrieval_before.raw_trace,
        "raw_trace_after": retrieval_after.raw_trace,
    }
    print(
        "AGENTENHANCE_WAVE3_ADAPTER_CHECK="
        + json.dumps(payload, sort_keys=True, default=str, allow_nan=False)
    )
    return 0 if payload["status"] == "LIFECYCLE_PASSED" else 4


if __name__ == "__main__":
    raise SystemExit(main())
