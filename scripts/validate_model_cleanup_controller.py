#!/usr/bin/env python3
"""Validate the frozen project-owned model cleanup controller."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons/model-cleanup-controller-prefreeze.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(entry: dict[str, object]) -> Path:
    path = ROOT / str(entry["path"])
    if not path.is_file() or sha256_file(path) != entry["sha256"]:
        raise SystemExit(f"cleanup controller dependency mismatch: {path}")
    return path


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_BEFORE_ANY_PROJECT_OWNED_MODEL_CLEANUP":
        raise SystemExit("cleanup controller contract status mismatch")
    policy = resolve(contract["parents"]["retention_policy"])
    ledger_path = resolve(contract["parents"]["ownership_ledger"])
    implementation = resolve(contract["implementation"])
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    aggregate = ledger["aggregate"]
    frozen = contract["parents"]["ownership_ledger"]
    if (
        aggregate["project_owned_candidate_models"] != frozen["project_owned_candidates"]
        or aggregate["project_owned_expected_bytes"] != frozen["expected_bytes"]
        or aggregate["currently_cleanup_eligible_models"] != frozen["currently_cleanup_eligible"]
    ):
        raise SystemExit("cleanup controller ownership cardinality mismatch")
    protected = "\n".join(contract["protected_assets"])
    if "Qwen3-VL-8B-Instruct" not in protected or "Qwen3-VL-Embedding-2B" not in protected:
        raise SystemExit("cleanup controller omits a protected shared model")
    source = implementation.read_text(encoding="utf-8")
    required = (
        "ELIGIBLE_PREFIXES",
        "validate_no_process_references",
        "lsof",
        "ONLY_RETIRED_ACCEPTED_DEPENDENTS",
        "os.rename",
        "shutil.rmtree",
        "verify_model_inventory",
        "DRY_RUN_ELIGIBLE",
        "QUARANTINED",
        "DELETED",
    )
    if not all(value in source for value in required):
        raise SystemExit("cleanup controller omits a two-phase safety control")
    if contract["implementation"]["phases"] != ["preflight", "quarantine", "delete"]:
        raise SystemExit("cleanup controller phase order mismatch")
    if len(contract["per_model_eligibility_record_required"]) < 8:
        raise SystemExit("cleanup eligibility record is underspecified")
    if not policy.is_file():
        raise SystemExit("retention policy missing")
    print(
        json.dumps(
            {
                "status": "PASS",
                "project_owned_candidates": frozen["project_owned_candidates"],
                "candidate_bytes": frozen["expected_bytes"],
                "currently_cleanup_eligible": frozen["currently_cleanup_eligible"],
                "phases": contract["implementation"]["phases"],
                "protected_shared_models": 2,
                "mutation_performed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
