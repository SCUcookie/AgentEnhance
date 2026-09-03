#!/usr/bin/env python3
"""Validate the prospective model ownership and cleanup-dependency ledger."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "comparisons/baseline-model-ownership-ledger.v1.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    assert ledger["status"] == "FROZEN_BEFORE_PROJECT_OWNED_MODEL_MATERIALIZATION"
    policy = ROOT / ledger["retention_policy"]["path"]
    assert ledger["retention_policy"]["sha256"] == sha256_file(policy)
    protected = ledger["protected_shared_assets"]
    assert len(protected) == 2
    assert all(row["ownership"] == "SHARED_PREEXISTING" for row in protected)
    assert all(row["cleanup_eligible"] is False for row in protected)
    candidates = ledger["project_owned_candidates"]
    assert len(candidates) == 7
    assert len({row["model_id"] for row in candidates}) == 7
    assert len({row["target"] for row in candidates}) == 7
    expected_files = 0
    expected_bytes = 0
    dependent_ids = set()
    for row in candidates:
        manifest_path = ROOT / row["prefetch_manifest"]
        assert row["prefetch_manifest_sha256"] == sha256_file(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        matches = [
            model
            for model in manifest["models"]
            if model["repository"] == row["repository"] and model["revision"] == row["revision"]
        ]
        assert len(matches) == 1
        model = matches[0]
        assert row["target"] == model["expected_local_path"]
        assert row["expected_files"] == model["expected_file_count"]
        assert row["expected_bytes"] == model["expected_total_bytes"]
        assert row["target"].startswith(
            "${AGENT_ENHANCE_REMOTE_ROOT}/cache/models/wma-r1-"
        )
        assert row["ownership_state"] == (
            "PROJECT_OWNED_CANDIDATE_IF_CREATED_BY_FROZEN_MATERIALIZER"
        )
        assert row["current_state"] == "NOT_MATERIALIZED_NOT_CLEANUP_ELIGIBLE"
        assert row["required_dependents"]
        dependent_ids.update(row["required_dependents"])
        dependent_ids.update(row["conservative_endpoint_dependents"])
        expected_files += row["expected_files"]
        expected_bytes += row["expected_bytes"]
    aggregate = ledger["aggregate"]
    assert aggregate == {
        "project_owned_candidate_models": 7,
        "project_owned_expected_files": expected_files,
        "project_owned_expected_bytes": expected_bytes,
        "protected_shared_models": 2,
        "currently_cleanup_eligible_models": 0,
    }
    assert (expected_files, expected_bytes) == (90, 26623841724)
    assert dependent_ids == {
        "wma-mirix",
        "wma-ngmemory",
        "wma-augustus",
        "wma-universalrag",
        "wma-qwen3-vl-embedding-8b",
        "wma-memoryos",
        "wma-memgas",
        "wma-hindsight",
        "wma-structmem",
    }
    assert len(ledger["state_transitions"]) == 6
    assert "authorizes no deletion" in ledger["deletion_boundary"]
    serialized = LEDGER.read_text(encoding="utf-8")
    assert "/data1/" not in serialized and "/data2/" not in serialized
    print(
        json.dumps(
            {
                "status": "PASS",
                "project_owned_candidates": len(candidates),
                "protected_shared_models": len(protected),
                "candidate_bytes": expected_bytes,
                "dependent_methods": len(dependent_ids),
                "cleanup_eligible_now": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
