#!/usr/bin/env python3
"""Validate the frozen result-free Mem-Gallery dataset projection loader."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "comparisons/memgallery-dataset-projection-loader-prefreeze.v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("memgallery_dataset_projection_loader", path)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load Mem-Gallery projection loader")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_IMPLEMENTATION_SYNTHETIC_ONLY_NO_REAL_DATA_ACCESSED":
        raise SystemExit("Mem-Gallery projection-loader state drift")
    for parent in contract["bound_inputs"]:
        if sha256(ROOT / parent["path"]) != parent["sha256"]:
            raise SystemExit(f"Mem-Gallery projection-loader parent drift: {parent['path']}")
    implementation = contract["implementation"]
    implementation_path = ROOT / implementation["path"]
    if sha256(implementation_path) != implementation["sha256"]:
        raise SystemExit("Mem-Gallery projection-loader implementation drift")
    test = contract["synthetic_test"]
    test_path = ROOT / test["path"]
    if sha256(test_path) != test["sha256"]:
        raise SystemExit("Mem-Gallery projection-loader test drift")
    if not (test_path.read_text(encoding="utf-8").count("    def test_") == test["tests"] == 6):
        raise SystemExit("Mem-Gallery projection-loader test count drift")

    module = load_module(implementation_path)
    identity = contract["fixed_dataset_identity"]
    if (
        module.EXPECTED_REPOSITORY != identity["repository"]
        or module.EXPECTED_REVISION != identity["revision"]
        or not (module.EXPECTED_SCENARIOS == identity["scenarios"] == 20)
        or not (module.EXPECTED_QUESTIONS == identity["questions"] == 1711)
        or not (module.EXPECTED_IMAGE_FILES == identity["image_files"] == 1490)
    ):
        raise SystemExit("Mem-Gallery projection-loader fixed identity drift")
    source = implementation_path.read_text(encoding="utf-8")
    required_tokens = (
        "load_dataset_evidence",
        "validate_manifest",
        "_verify_manifest_member",
        "validate_query_projection",
        "_assert_answer_free",
        "allowed_image_sha256",
        '"raw_answers_returned": 0',
        '"scores_observed": 0',
        '"filesystem_mutations": 0',
    )
    if any(token not in source for token in required_tokens):
        raise SystemExit("Mem-Gallery projection-loader enforcement surface drift")
    forbidden_tokens = ("urllib", "requests.", "subprocess", ".write_text(", ".write_bytes(", ".mkdir(", ".unlink(")
    if any(token in source for token in forbidden_tokens):
        raise SystemExit("Mem-Gallery projection loader gained network or mutation behavior")
    accepted = contract["accepted_bundle"]
    if (
        accepted["status"] != "ACCEPTED_ANSWER_FREE_PROJECTION"
        or accepted["raw_answers_returned"] != 0
        or accepted["scores_observed"] != 0
        or accepted["filesystem_mutations"] != 0
    ):
        raise SystemExit("Mem-Gallery projection-loader evidence boundary drift")
    current = contract["current_state"]
    if (
        current["real_dataset_materialized"]
        or current["real_projection_bundle_created"]
        or current["real_run_roots_created"] != 0
        or current["real_predictions_written"] != 0
        or current["scores_observed"] != 0
    ):
        raise SystemExit("Mem-Gallery projection-loader current-state disclosure drift")
    print(json.dumps({
        "status": "PASS",
        "scenarios": identity["scenarios"],
        "questions": identity["questions"],
        "image_files": identity["image_files"],
        "synthetic_tests": test["tests"],
        "real_dataset_accesses": implementation["real_dataset_accesses_at_freeze"],
        "raw_answers_returned": accepted["raw_answers_returned"],
        "scores_observed": accepted["scores_observed"],
        "contract_sha256": sha256(CONTRACT_PATH),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
