#!/usr/bin/env python3
"""Static tests for the frozen Wave-1 postprocess matrix."""

from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("wave1_postprocess", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = load_module(ROOT / "scripts/remote_wma_wave1_postprocess.py")
    expected = module.expected_progress_rows()
    plan = module.build_plan()
    assert len(expected) == 12
    assert len(plan) == 4
    assert {item["implementation_id"] for item in plan} == {
        "wma-mmfu-single",
        "wma-simplemem",
        "wma-m2a",
        "wma-vilomem",
    }
    assert all(len(item["aggregate_roots"]) == 3 for item in plan)
    roots = [str(root) for item in plan for root in item["aggregate_roots"]]
    assert len(roots) == len(set(roots)) == 12
    assert all(root.startswith("/data1/2026/ldh/AgentEnhance/runs/") for root in roots)
    assert all(root.endswith("-aggregate") for root in roots)
    assert all(str(item["output_root"]).startswith(str(module.OUTPUT_ROOT)) for item in plan)
    manifest = json.loads(
        (ROOT / "comparisons/wma-r1-wave1-postprocess-prefreeze.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["status"] == "FROZEN_BEFORE_WAVE1_TERMINAL"
    assert manifest["inputs"]["aggregate_roots"] == 12
    assert manifest["inputs"]["methods"] == [item["implementation_id"] for item in plan]
    assert manifest["fresh_output_root"] == str(module.OUTPUT_ROOT)
    assert manifest["implementation"]["combine_script_sha256"] == module.COMBINE_SCRIPT_SHA256
    postprocessor = ROOT / manifest["implementation"]["postprocessor"]
    assert hashlib.sha256(postprocessor.read_bytes()).hexdigest() == manifest["implementation"][
        "postprocessor_sha256"
    ]
    print("wave1-postprocess-static-test=PASS methods=4 seeds=3 roots=12")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
