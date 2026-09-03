#!/usr/bin/env python3
"""Run one auditable Wave-2 WorldMemArena adapter lifecycle observation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any


IMAGE_REQUIRED = frozenset(
    {
        "Omni-SimpleMem",
        "NGMemory",
        "AUGUSTUSMemory",
        "UniversalRAGMemory",
        "Qwen3-VL-Embedding-8B",
    }
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact_snapshot(row: Any) -> dict[str, Any]:
    return {
        "memory_id": str(row.memory_id),
        "raw_backend_type": row.raw_backend_type,
        "text_nonempty": bool(str(row.text).strip()),
        "metadata_keys": sorted(str(key) for key in row.metadata),
        "modality": row.metadata.get("modality"),
    }


def compact_retrieval(row: Any) -> dict[str, Any]:
    return {
        "rank": int(row.rank),
        "memory_id": str(row.memory_id),
        "text_nonempty": bool(str(row.text).strip()),
        "image_path": row.image_path,
        "score": float(row.score),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--image-path", type=Path, required=True)
    parser.add_argument("--image-sha256", required=True)
    parser.add_argument("--image-id", default="eb_alfred_base_01_img_001")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    image_path = args.image_path.resolve()
    if not (repo_root / "eval_framework" / "memory_adapters" / "registry.py").is_file():
        raise SystemExit(f"not a WorldMemArena checkout: {repo_root}")
    if not image_path.is_file():
        raise SystemExit(f"missing lifecycle image: {image_path}")
    observed_image_sha256 = sha256_file(image_path)
    if observed_image_sha256 != args.image_sha256:
        raise SystemExit("lifecycle image digest mismatch")

    os.chdir(repo_root)
    sys.path.insert(0, str(repo_root))
    from eval_framework.datasets.schemas import Attachment, NormalizedTurn
    from eval_framework.memory_adapters.registry import (
        MEMGALLERY_NATIVE_BASELINES,
        create_external_adapter,
        create_memgallery_adapter,
    )

    if args.baseline in MEMGALLERY_NATIVE_BASELINES:
        adapter = create_memgallery_adapter(args.baseline)
    else:
        adapter = create_external_adapter(args.baseline)
    capabilities = adapter.get_capabilities()
    adapter.reset()

    session_id = "wave2-lifecycle-session"
    attachment = Attachment(
        caption=(
            "A top-down view of a wooden desk with a lit lamp, a gray bowl, "
            "chairs, a CD, and a small rectangular object."
        ),
        type="image_caption",
        image_id=args.image_id,
        file_path=str(image_path),
    )
    adapter.ingest_turn(
        NormalizedTurn(
            sample_id="wave2-lifecycle-sample",
            session_id=session_id,
            turn_index=0,
            role="user",
            text=(
                "Remember that the private project code is blue-orchid-739. "
                "The attached image is the fixed visual evidence for this memory."
            ),
            attachments=(attachment,),
            timestamp="2026-09-03T00:00:00Z",
        )
    )
    adapter.ingest_turn(
        NormalizedTurn(
            sample_id="wave2-lifecycle-sample",
            session_id=session_id,
            turn_index=1,
            role="assistant",
            text="I will retain the code and its associated visual evidence.",
            timestamp="2026-09-03T00:00:01Z",
        )
    )
    adapter.end_session(session_id)
    snapshot = adapter.snapshot_memories()
    fact_retrieval = adapter.retrieve(
        "What is the private project code?", top_k=3
    )
    visual_retrieval = adapter.retrieve(
        "Which memory is associated with the desk and lamp image?", top_k=3
    )

    retrieval_items = list(fact_retrieval.items) + list(visual_retrieval.items)
    image_reference_observed = any(
        item.image_path and Path(item.image_path).resolve() == image_path
        for item in retrieval_items
    ) or any(
        row.metadata.get("modality") in {"visual", "image"}
        or args.image_id in json.dumps(row.metadata, sort_keys=True, default=str)
        for row in snapshot
    )
    snapshot_text_nonempty = sum(bool(str(row.text).strip()) for row in snapshot)
    partitions = sorted(
        {
            str(row.metadata.get("partition"))
            for row in snapshot
            if row.metadata.get("partition")
        }
    )
    invariants: dict[str, bool] = {
        "snapshot_nonempty": bool(snapshot),
        "snapshot_text_nonempty": snapshot_text_nonempty > 0,
        "fact_retrieval_nonempty": bool(fact_retrieval.items),
        "visual_retrieval_nonempty": bool(visual_retrieval.items),
        "fixed_image_digest_verified": True,
        "retrieval_scores_finite": all(
            math.isfinite(float(item.score)) for item in retrieval_items
        ),
    }
    if args.baseline in IMAGE_REQUIRED:
        invariants["image_reference_observed"] = image_reference_observed
    if args.baseline == "A-Mem":
        invariants["extracted_metadata_observed"] = any(
            any(row.metadata.get(key) for key in ("context", "keywords", "tags", "category"))
            for row in snapshot
        )
    if args.baseline == "MIRIX":
        invariants["mirix_partition_observed"] = bool(partitions)

    payload = {
        "schema_version": "agentenhance.wma_wave2_adapter_lifecycle.v1",
        "status": "LIFECYCLE_PASSED" if all(invariants.values()) else "LIFECYCLE_REJECTED",
        "baseline": args.baseline,
        "adapter_class": type(adapter).__name__,
        "capabilities": capabilities,
        "fixed_image": {
            "path": str(image_path),
            "image_id": args.image_id,
            "sha256": observed_image_sha256,
        },
        "counts": {
            "snapshot": len(snapshot),
            "snapshot_text_nonempty": snapshot_text_nonempty,
            "fact_retrieval": len(fact_retrieval.items),
            "visual_retrieval": len(visual_retrieval.items),
        },
        "mirix_partitions": partitions,
        "image_reference_observed": image_reference_observed,
        "invariants": invariants,
        "snapshot_preview": [compact_snapshot(row) for row in snapshot[:10]],
        "fact_retrieval_preview": [
            compact_retrieval(row) for row in fact_retrieval.items[:3]
        ],
        "visual_retrieval_preview": [
            compact_retrieval(row) for row in visual_retrieval.items[:3]
        ],
        "raw_traces": {
            "fact": fact_retrieval.raw_trace,
            "visual": visual_retrieval.raw_trace,
        },
    }
    print(
        "AGENTENHANCE_WAVE2_ADAPTER_CHECK="
        + json.dumps(payload, sort_keys=True, default=str, allow_nan=False)
    )
    return 0 if payload["status"] == "LIFECYCLE_PASSED" else 4


if __name__ == "__main__":
    raise SystemExit(main())
