#!/usr/bin/env python3
"""Validate source-reported baseline values without treating them as reproductions."""

from __future__ import annotations

import csv
import math
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_RESULTS = ROOT / "comparisons" / "source-reported-results.v1.csv"


def fail(message: str) -> None:
    raise SystemExit(f"source-result validation failed: {message}")


def main() -> int:
    with SOURCE_RESULTS.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    required = {
        "benchmark",
        "protocol_id",
        "n",
        "method_id",
        "metric",
        "value",
        "direction",
        "source_type",
        "source_locator",
        "source_commit",
        "comparison_eligibility",
        "notes",
    }
    if not rows:
        fail("no source-reported rows")
    if set(rows[0]) != required:
        fail(f"unexpected columns: {sorted(set(rows[0]) ^ required)}")

    keys: set[tuple[str, str, str, str]] = set()
    for index, row in enumerate(rows, start=2):
        key = (row["benchmark"], row["protocol_id"], row["method_id"], row["metric"])
        if key in keys:
            fail(f"duplicate result key on line {index}: {key}")
        keys.add(key)
        try:
            n = int(row["n"])
            value = float(row["value"])
        except ValueError as exc:
            fail(f"invalid numeric field on line {index}: {exc}")
        if n <= 0 or not math.isfinite(value):
            fail(f"nonpositive n or nonfinite value on line {index}")
        if row["direction"] not in {"higher", "lower"}:
            fail(f"invalid direction on line {index}")
        if row["comparison_eligibility"] != "source_only":
            fail(f"source value incorrectly comparison-eligible on line {index}")
        if len(row["source_commit"]) != 40:
            fail(f"source commit is not a full SHA on line {index}")

    protocols = Counter(row["protocol_id"] for row in rows)
    if len(rows) < 60 or len(protocols) < 3:
        fail("source table is unexpectedly narrow")
    print(
        f"PASS rows={len(rows)} protocols={len(protocols)} "
        f"benchmarks={len(set(row['benchmark'] for row in rows))}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
