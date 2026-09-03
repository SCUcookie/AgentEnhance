#!/usr/bin/env python3
"""Verify sufficient-stat formulas against four stored WMA smoke aggregates."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from wma_pairwise_sufficient_stats import PAIRED_METRIC_KEYS, aggregate_record_stats


METHOD_DIRS = ("mmfu_single", "simplemem", "m2a", "vilomem")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def nested(payload: dict[str, Any], key: str) -> float:
    value: Any = payload
    for part in key.split("."):
        value = value[part]
    return float(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-root", type=Path, required=True)
    args = parser.parse_args()
    checked = 0
    for method in METHOD_DIRS:
        output = args.smoke_root / method / "output"
        qa = read_jsonl(output / "qa_records.jsonl")
        sessions = read_jsonl(output / "session_records.jsonl")
        aggregate = json.loads((output / "aggregate_metrics.json").read_text(encoding="utf-8"))
        stats = aggregate_record_stats(qa, sessions)
        for key in PAIRED_METRIC_KEYS:
            expected = nested(aggregate, key)
            actual = stats[key].value
            if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12):
                raise SystemExit(
                    f"aggregate mismatch {method}:{key}: expected={expected}, actual={actual}"
                )
            checked += 1
    print(f"wma-sufficient-stat-validation=PASS methods=4 metric_checks={checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
