#!/usr/bin/env python3
"""Validate the frozen post-materialization Mem-Gallery integrity contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "memgallery-data-integrity-prefreeze.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    contract = json.loads(PATH.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_AWAITING_ACCEPTED_MATERIALIZATION":
        raise SystemExit("Mem-Gallery integrity stage is not frozen before materialization")
    for row in contract["bound_inputs"]:
        if sha256_file(ROOT / row["path"]) != row["sha256"]:
            raise SystemExit(f"bound integrity input drift: {row['path']}")

    upstream = contract["upstream_runner_alignment"]
    if (
        upstream["commit"] != "a93959e1e978a6a7d77798ae92c2ffe41c538c62"
        or upstream["path"] != "benchmark/run/run_bench.py"
        or upstream["question_id_scheme"] != "<dialog filename stem>:<zero-based QA index>"
    ):
        raise SystemExit("upstream runner traversal identity drift")
    for phrase in ("absolute paths", "traversal", "symlinks", "every image-list element"):
        if phrase not in upstream["strictness_delta"]:
            raise SystemExit(f"missing runner strictness boundary: {phrase}")

    dataset = contract["dataset_identity"]
    observed = tuple(dataset[key] for key in ("revision", "files", "bytes", "dialog_files", "image_files", "questions"))
    expected = ("af912daba984e896e253016b7c7e334ef92c2a6f", 1515, 545845389, 20, 1490, 1711)
    if observed != expected:
        raise SystemExit("integrity dataset identity drift")
    for key in ("sessions", "dialogue_rounds", "runner_consumed_dialogue_rounds"):
        if dataset[key] != "MEASURE_AFTER_MATERIALIZATION":
            raise SystemExit(f"non-observed dataset count was prematurely frozen: {key}")

    paths = contract["paths"]
    if paths["dataset_root"] != "/data1/2026/ldh/AgentEnhance/datasets/raw/mem-gallery-af912dab":
        raise SystemExit("dataset root drift")
    if paths["evidence_root"] != "/data1/2026/ldh/AgentEnhance/runs/mem-gallery-data-integrity-af912dab-20260904-v1":
        raise SystemExit("integrity evidence root drift")
    argv = contract["execution"]["argv"]
    required = {
        "--dataset-root": paths["dataset_root"],
        "--manifest": "comparisons/memgallery-data-prefetch-manifest.v1.json",
        "--evidence-root": paths["evidence_root"],
        "--required-marker": paths["materialization_evidence_root"] + "/TERMINAL_ACCEPTED",
        "--forbidden-marker": paths["materialization_evidence_root"] + "/TERMINAL_REJECTED",
        "--expected-questions": "1711",
    }
    for flag, value in required.items():
        index = argv.index(flag)
        if argv[index + 1] != value:
            raise SystemExit(f"integrity argv drift: {flag}")
    execution = contract["execution"]
    if any(execution[key] != 0 for key in ("network_requests", "gpu_processes", "dataset_writes", "numeric_result_rows")):
        raise SystemExit("integrity stage includes a prohibited mutation or numerical run")

    if set(contract["stable_outputs"]) != {
        "dataset-integrity.json",
        "question-index.jsonl",
        "QID_ORDER.txt",
        "image-references.json",
        "EVIDENCE_SHA256SUMS",
        "TERMINAL_ACCEPTED",
    }:
        raise SystemExit("integrity evidence inventory drift")
    for phrase in ("1515 paths", "1711", "1490 image paths", "TERMINAL_ACCEPTED"):
        if phrase not in contract["acceptance_rule"]:
            raise SystemExit(f"missing integrity acceptance condition: {phrase}")
    if "No Mem-Gallery method may begin" not in contract["downstream_gate"]:
        raise SystemExit("integrity audit does not gate downstream methods")
    if "SOTA claim" not in contract["scientific_boundary"]:
        raise SystemExit("integrity scientific boundary is incomplete")

    print(
        json.dumps(
            {
                "status": "PASS",
                "contract_sha256": sha256_file(PATH),
                "audit_script_sha256": sha256_file(ROOT / "scripts" / "audit_memgallery_dataset.py"),
                "questions": dataset["questions"],
                "network_requests": execution["network_requests"],
                "numeric_rows": execution["numeric_result_rows"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
