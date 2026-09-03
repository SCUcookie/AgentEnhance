#!/usr/bin/env python3
"""Construct one frozen WorldMemArena adapter and emit a machine-readable check."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--lifecycle", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    if not (repo_root / "eval_framework" / "memory_adapters" / "registry.py").is_file():
        raise SystemExit(f"not a WorldMemArena checkout: {repo_root}")
    os.chdir(repo_root)
    sys.path.insert(0, str(repo_root))

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
    payload = {
        "schema_version": "agentenhance.wma_adapter_smoke.v1",
        "status": "CONSTRUCTED",
        "baseline": args.baseline,
        "adapter_class": type(adapter).__name__,
        "capabilities": capabilities,
    }
    if args.lifecycle:
        from eval_framework.datasets.schemas import NormalizedTurn

        session_id = "adapter-smoke-session"
        adapter.ingest_turn(
            NormalizedTurn(
                sample_id="adapter-smoke-sample",
                session_id=session_id,
                turn_index=0,
                role="user",
                text="Remember that the private project code is blue-orchid-739.",
                timestamp="2026-09-03T00:00:00Z",
            )
        )
        adapter.ingest_turn(
            NormalizedTurn(
                sample_id="adapter-smoke-sample",
                session_id=session_id,
                turn_index=1,
                role="assistant",
                text="I will remember the project code.",
                timestamp="2026-09-03T00:00:01Z",
            )
        )
        adapter.end_session(session_id)
        snapshot = adapter.snapshot_memories()
        retrieval = adapter.retrieve("What is the private project code?", top_k=3)
        if not snapshot:
            raise RuntimeError("lifecycle produced an empty memory snapshot")
        if not retrieval.items:
            raise RuntimeError("lifecycle produced an empty retrieval")
        payload["status"] = "LIFECYCLE_PASSED"
        payload["lifecycle"] = {
            "snapshot_count": len(snapshot),
            "retrieval_count": len(retrieval.items),
            "top_text": retrieval.items[0].text,
        }
    print("AGENTENHANCE_ADAPTER_CHECK=" + json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
