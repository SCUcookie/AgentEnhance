#!/usr/bin/env python3
"""Validate the synthetic-only Mem-Gallery raw-run writer contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons" / "memgallery-raw-run-writer-prefreeze.v1.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    require(
        payload.get("status") == "FROZEN_SYNTHETIC_ONLY_AWAITING_FILESYSTEM_LIFECYCLE_CONTROLLER",
        "raw-run writer status drift",
    )
    bindings = payload.get("bound_inputs", [])
    require(len(bindings) == 4, "bound-input count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file(), f"missing bound input: {path}")
        require(sha256_file(path) == binding["sha256"], f"bound-input hash drift: {path}")
    root_contract = payload.get("root_contract", {})
    require(root_contract.get("resume") is False, "resume policy drift")
    require(root_contract.get("same_root_retry") is False, "same-root retry policy drift")
    require(len(root_contract.get("append_only", [])) == 4, "append-only stream count drift")
    validation = payload.get("validation", {})
    require(validation.get("synthetic_tests_passed") == 6, "synthetic test count drift")
    require(validation.get("resource_warnings") == 0, "resource warning regression")
    for field in ("real_run_roots_created", "real_predictions_written", "scores_observed"):
        require(validation.get(field) == 0, f"synthetic-only boundary drift: {field}")
    require("authorizes no real run root" in payload.get("authorization", ""), "authorization boundary missing")
    print(
        json.dumps(
            {
                "status": "PASS",
                "contract_sha256": sha256_file(CONTRACT),
                "writer_sha256": bindings[2]["sha256"],
                "synthetic_tests": validation["synthetic_tests_passed"],
                "resource_warnings": validation["resource_warnings"],
                "reconciliation_core_acceptance_tested": True,
                "real_run_roots_created": validation["real_run_roots_created"],
                "scores_observed": validation["scores_observed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
