#!/usr/bin/env python3
"""Validate the synthetic-only Mem-Gallery lifecycle controller contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons" / "memgallery-lifecycle-controller-prefreeze.v1.json"


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
    require(payload.get("status") == "FROZEN_SYNTHETIC_ONLY_AWAITING_WAVE1_RELEASE", "lifecycle status drift")
    bindings = payload.get("bound_inputs", [])
    require(len(bindings) == 5, "bound-input count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file(), f"missing bound input: {path}")
        require(sha256_file(path) == binding["sha256"], f"bound-input hash drift: {path}")
    surface = payload.get("registered_surface", {})
    require(surface.get("scenarios") == 20, "scenario denominator drift")
    require(surface.get("questions") == 1711, "question denominator drift")
    require(surface.get("models") == 5, "model receipt count drift")
    validation = payload.get("validation", {})
    require(validation.get("synthetic_tests_passed") == 6, "synthetic test count drift")
    for field in ("real_run_roots_created", "real_model_calls", "scores_observed"):
        require(validation.get(field) == 0, f"synthetic-only boundary drift: {field}")
    require(payload.get("authorization", {}).get("real_mode_implemented") is False, "real mode boundary drift")
    print(json.dumps({"status": "PASS", "contract_sha256": sha256_file(CONTRACT), "controller_sha256": bindings[3]["sha256"], "synthetic_tests": 6, "real_mode_implemented": False, "scores_observed": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
