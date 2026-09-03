#!/usr/bin/env python3
"""Classify WMA methods as deterministic only when three semantic digests match."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


METHODS = ("mmfu_single", "simplemem", "m2a", "vilomem")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("gate_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing existing output: {args.output}")

    methods: dict[str, object] = {}
    for method in METHODS:
        reports = []
        for replicate in (1, 2, 3):
            path = args.gate_root / "semantic-digests" / f"replicate-{replicate}" / f"{method}.json"
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        combined = [str(report["combined_semantic_sha256"]) for report in reports]
        methods[method] = {
            "replicates": 3,
            "combined_semantic_sha256": combined,
            "byte_identical_semantics": len(set(combined)) == 1,
            "full_run_seed_policy": "one deterministic run" if len(set(combined)) == 1 else "three independent seeded runs",
        }

    report = {
        "schema_version": "agentenhance.wma_determinism_gate_audit.v1",
        "status": "TERMINAL_ACCEPTED",
        "methods": methods,
        "decision_rule_applied": True,
        "all_methods_deterministic": all(
            bool(value["byte_identical_semantics"]) for value in methods.values()
        ),
        "claim_scope": "execution multiplicity only; no benchmark score or method ranking",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
