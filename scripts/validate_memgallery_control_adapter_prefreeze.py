#!/usr/bin/env python3
"""Validate the frozen answer-isolating Mem-Gallery control adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons" / "memgallery-control-adapter-prefreeze.v1.json"


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
    require(payload.get("status") == "FROZEN_PROJECTION_ONLY_AWAITING_ACCEPTED_DATASET", "status drift")
    upstream = payload.get("upstream_authority", {})
    require(upstream.get("revision") == "a93959e1e978a6a7d77798ae92c2ffe41c538c62", "upstream revision drift")
    require(upstream.get("sha256") == "1c92b38ade1613ad699f297bb3f1ac346bbdfa5889828d1d3ac92e6c4fb7ac3e", "upstream entrypoint drift")
    bindings = payload.get("bound_inputs", [])
    require(len(bindings) == 4, "bound-input count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file(), f"missing bound input: {path}")
        require(sha256_file(path) == binding["sha256"], f"bound-input hash drift: {path}")
    question = payload.get("question_projection", {})
    require("returns no raw answer field" in question.get("answer_isolation", ""), "answer isolation drift")
    validation = payload.get("validation", {})
    require(validation.get("synthetic_tests_passed") == 5, "test count drift")
    for field in ("real_dataset_rows_read", "raw_answers_emitted", "network_requests", "gpu_processes", "predictions_observed", "scores_observed"):
        require(validation.get(field) == 0, f"projection-only boundary drift: {field}")
    require("does not authorize" in payload.get("authorization", ""), "authorization boundary missing")
    print(json.dumps({
        "status": "PASS",
        "contract_sha256": sha256_file(CONTRACT),
        "adapter_sha256": bindings[2]["sha256"],
        "synthetic_tests": validation["synthetic_tests_passed"],
        "raw_answers_emitted": validation["raw_answers_emitted"],
        "scores_observed": validation["scores_observed"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
