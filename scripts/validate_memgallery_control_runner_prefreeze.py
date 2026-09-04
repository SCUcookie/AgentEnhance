#!/usr/bin/env python3
"""Validate the result-free Mem-Gallery control runner composition."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons" / "memgallery-control-runner-prefreeze.v1.json"
EXPECTED = [
    "no-memory",
    "full-memory-text",
    "full-memory-mm",
    "fifo-recent",
    "bm25",
    "naive-rag",
    "hybrid-rag",
]


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
        payload.get("status") == "FROZEN_COMPOSITION_ONLY_AWAITING_REAL_LIFECYCLE_AUTHORIZATION",
        "runner-composition status drift",
    )
    require(payload.get("registered_controls") == EXPECTED, "control surface drift")
    bindings = payload.get("bound_inputs", [])
    require(len(bindings) == 7, "bound-input count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file(), f"missing bound input: {path}")
        require(sha256_file(path) == binding["sha256"], f"bound-input hash drift: {path}")
    failure = payload.get("failure_contract", {})
    require(failure.get("same_root_retry") is False, "same-root retry must remain prohibited")
    require("Every input query yields exactly one" in failure.get("denominator", ""), "denominator rule drift")
    require(payload.get("output_contract", {}).get("scores_observed") == 0, "output score boundary drift")
    validation = payload.get("validation", {})
    require(validation.get("synthetic_composition_tests_passed") == 6, "composition test count drift")
    for field in ("real_scenarios_read", "real_questions_read", "real_model_calls", "predictions_observed", "scores_observed"):
        require(validation.get(field) == 0, f"composition-only boundary drift: {field}")
    print(
        json.dumps(
            {
                "status": "PASS",
                "contract_sha256": sha256_file(CONTRACT),
                "runner_sha256": bindings[5]["sha256"],
                "controls": len(EXPECTED),
                "synthetic_tests": validation["synthetic_composition_tests_passed"],
                "real_model_calls": validation["real_model_calls"],
                "scores_observed": validation["scores_observed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
