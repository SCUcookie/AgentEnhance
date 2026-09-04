#!/usr/bin/env python3
"""Validate the result-free Causal-LoCoMo main table proposal."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "comparisons" / "causal-locomo-main-table-spec-proposal.v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("state") != "PROPOSED_RESULT_FREE_NOT_FROZEN_NOT_AUTHORIZED":
        raise SystemExit("Causal-LoCoMo table state drift")
    for parent in spec["parents"]:
        if sha256(ROOT / parent["path"]) != parent["sha256"]:
            raise SystemExit(f"Causal-LoCoMo table parent drift: {parent['path']}")
    table_path = ROOT / spec["template"]
    with table_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if [row["method_id"] for row in rows] != spec["row_order"] or len(rows) != 8:
        raise SystemExit("Causal-LoCoMo table row order drift")
    metric_fields = [field for panel in spec["metric_panels"].values() for field in panel]
    if len(metric_fields) != 21 or len(metric_fields) != len(set(metric_fields)):
        raise SystemExit("Causal-LoCoMo metric surface drift")
    if any(field not in rows[0] for field in metric_fields):
        raise SystemExit("Causal-LoCoMo table lacks a registered metric column")
    if any(row[field] != "" for row in rows for field in metric_fields):
        raise SystemExit("Causal-LoCoMo result-free table contains a numeric metric")
    if any(row["registered_rows"] != "261" for row in rows):
        raise SystemExit("Causal-LoCoMo denominator drift")
    status = {row["method_id"]: row["comparison_status"] for row in rows}
    if (
        status["cmi-reflection-memory"] != "PROTOCOL_BLOCKED"
        or status["cmi"] != "PROTOCOL_BLOCKED"
        or status["agentenhance-ceu"] != "LOCKED_UNTIL_BASELINE_GATE"
    ):
        raise SystemExit("Causal-LoCoMo blocker or AgentEnhance gate drift")
    numeric = spec["current_numeric_state"]
    if any(value != 0 for value in numeric.values()):
        raise SystemExit("Causal-LoCoMo table proposal contains observed values")
    print(json.dumps({
        "status": "PASS",
        "methods": len(rows),
        "metrics": len(metric_fields),
        "populated_metric_cells": numeric["populated_metric_cells"],
        "template_sha256": sha256(table_path),
        "spec_sha256": sha256(SPEC),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
