#!/usr/bin/env python3
"""Validate the pre-result Wave1 recovery2 closure chain."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CONTRACT = ROOT / "comparisons/wma-r1-wave1-recovery2-closure-prefreeze.v1.json"
sys.path.insert(0, str(SCRIPTS))
from frozen_source_successor import render_successor  # noqa: E402


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load wrapper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_BEFORE_WAVE1_RECOVERY2_TERMINAL":
        raise SystemExit("recovery2 closure is not pre-result frozen")
    renderer = ROOT / contract["successor_renderer"]["path"]
    if sha256_file(renderer) != contract["successor_renderer"]["sha256"]:
        raise SystemExit("successor renderer digest mismatch")
    if [stage["order"] for stage in contract["stages"]] != [1, 2, 3, 4]:
        raise SystemExit("closure stage order mismatch")
    rendered: dict[str, str] = {}
    for stage in contract["stages"]:
        parent = ROOT / stage["parent"]["path"]
        wrapper_path = ROOT / stage["wrapper"]["path"]
        if sha256_file(parent) != stage["parent"]["sha256"]:
            raise SystemExit(f"closure parent digest mismatch: {stage['name']}")
        if sha256_file(wrapper_path) != stage["wrapper"]["sha256"]:
            raise SystemExit(f"closure wrapper digest mismatch: {stage['name']}")
        wrapper = load_module(wrapper_path)
        source = render_successor(
            parent,
            wrapper.PARENT_SHA256,
            wrapper.REPLACEMENTS,
            wrapper.RENDERED_SHA256,
        )
        if wrapper.RENDERED_SHA256 != stage["wrapper"]["rendered_sha256"]:
            raise SystemExit(f"rendered successor digest mismatch: {stage['name']}")
        compile(source, f"<{stage['name']}>", "exec")
        rendered[stage["name"]] = wrapper.RENDERED_SHA256
    test = ROOT / contract["test"]["path"]
    if sha256_file(test) != contract["test"]["sha256"]:
        raise SystemExit("closure test digest mismatch")
    inherited = contract["inherited_scientific_contract"]
    if (
        len(inherited["methods"]) != 4
        or inherited["seeds"] != [0, 1, 2]
        or inherited["samples_per_seed"] != 150
        or inherited["qa_per_seed"] != 7906
        or inherited["failed_samples_per_seed"] != 0
        or inherited["official_values_used"] is not False
    ):
        raise SystemExit("closure scientific surface mismatch")
    if contract["runtime_state_at_freeze"]["complete_seed_results"] != 0:
        raise SystemExit("closure was not frozen before complete seed results")
    print(
        json.dumps(
            {
                "status": "PASS",
                "closure_stages": len(contract["stages"]),
                "rendered_successors": rendered,
                "accepted_methods": 4,
                "aggregate_roots": 12,
                "archives": 6,
                "official_values_used": False,
                "numeric_rows_at_freeze": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
