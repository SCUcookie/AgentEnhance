#!/usr/bin/env python3
"""Validate the zero-retry Wave3 and Hindsight model-acquisition successors."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOWNLOADER = ROOT / "scripts/materialize_hf_model_snapshot_v3.py"
TEST = ROOT / "tests/test_hf_model_materializer_v3.py"
SUCCESSORS = (
    ROOT / "comparisons/wma-r1-wave3-model-materialization-prefreeze.v2.json",
    ROOT / "comparisons/wma-r1-wave4-hindsight-model-materialization-prefreeze.v2.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    expected_downloader_sha = sha256_file(DOWNLOADER)
    expected_test_sha = sha256_file(TEST)
    model_count = 0
    file_count = 0
    total_bytes = 0
    for path in SUCCESSORS:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["status"] == "FROZEN_AWAITING_WAVE1_RESOURCE_GATE"
        assert payload["supersedes"]["prior_execution_performed"] is False
        prior = ROOT / payload["supersedes"]["path"]
        assert payload["supersedes"]["sha256"] == sha256_file(prior)
        source = ROOT / payload["source_manifest"]["path"]
        assert payload["source_manifest"]["sha256"] == sha256_file(source)
        source_payload = json.loads(source.read_text(encoding="utf-8"))
        models = {row["repository"]: row for row in source_payload["models"]}
        implementation = payload["implementation"]
        assert ROOT / implementation["downloader"] == DOWNLOADER
        assert implementation["downloader_sha256"] == expected_downloader_sha
        assert ROOT / implementation["unit_test"] == TEST
        assert implementation["unit_test_sha256"] == expected_test_sha
        assert implementation["unit_tests"] == 6
        assert payload["execution_contract"]["network_retry_count"] == 0
        assert payload["execution_contract"]["logical_requests_per_file"] == 1
        assert payload["scheduler"]["parallel_materializations"] == 1
        assert payload["scheduler"]["gpu_count"] == 0
        observed_files = 0
        observed_bytes = 0
        for row in payload["execution_order"]:
            model = models[row["repository"]]
            assert row["revision"] == model["revision"]
            assert row["target"] == model["expected_local_path"]
            assert row["expected_files"] == model["expected_file_count"]
            assert row["expected_bytes"] == model["expected_total_bytes"]
            paths = [item["path"] for item in model["expected_files"]]
            assert paths == sorted(paths) and len(paths) == len(set(paths))
            assert sum(item["bytes"] for item in model["expected_files"]) == row[
                "expected_bytes"
            ]
            observed_files += row["expected_files"]
            observed_bytes += row["expected_bytes"]
        assert observed_files == payload["source_manifest"]["exact_expected_files"]
        assert observed_bytes == payload["source_manifest"]["expected_total_bytes"]
        assert "/data1/" not in path.read_text(encoding="utf-8")
        assert "/data2/" not in path.read_text(encoding="utf-8")
        model_count += len(payload["execution_order"])
        file_count += observed_files
        total_bytes += observed_bytes
    print(
        json.dumps(
            {
                "status": "PASS",
                "successor_contracts": len(SUCCESSORS),
                "models": model_count,
                "expected_files": file_count,
                "expected_bytes": total_bytes,
                "network_retry_count": 0,
                "numeric_result_rows_added": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
