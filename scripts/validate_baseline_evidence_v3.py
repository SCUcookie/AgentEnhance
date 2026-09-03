#!/usr/bin/env python3
"""Validate the versioned baseline registry expansion without admitting results."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "comparisons" / "baseline-register.v2.csv"
V3 = ROOT / "comparisons" / "baseline-register.v3.csv"
AUDIT = ROOT / "comparisons" / "recent-2026-source-discovery-audit.v1.json"
RESULTS = ROOT / "comparisons" / "reproduced-results.v1.csv"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


with V2.open(encoding="utf-8", newline="") as handle:
    v2_rows = list(csv.DictReader(handle))
with V3.open(encoding="utf-8", newline="") as handle:
    v3_rows = list(csv.DictReader(handle))
audit = json.loads(AUDIT.read_text(encoding="utf-8"))

assert sha256_file(V2) == "8513ae3481e4329063c6eebd45ea03ae43a7888530960292f1eff4cf5aed9316"
assert sha256_file(AUDIT) == "3ac6b84145db52a3655ce1b9c3a65fad4ea9e1b9aea17c69edbded771fbb164e"
assert len(v2_rows) == 45
assert len(v3_rows) == 47
assert len({row["method_id"] for row in v3_rows}) == 47

v2_ids = {row["method_id"] for row in v2_rows}
v3_by_id = {row["method_id"]: row for row in v3_rows}
assert set(v3_by_id) - v2_ids == {"structmem", "hela-mem"}
assert v3_by_id["structmem"]["official_repo"] == "https://github.com/zjunlp/LightMem"
assert v3_by_id["structmem"]["adapter_status"] == "source-audit-required"
assert v3_by_id["hela-mem"]["adapter_status"] == "license-audit-blocked"
assert v3_by_id["memory-r1"]["adapter_status"] == "code-not-released"
assert v3_by_id["apex-mem"]["adapter_status"] == "no-official-code-verified"
assert v3_by_id["lightmem"]["adapter_status"] == "no-official-code-verified"

recent = [
    row
    for row in v3_rows
    if row["year"] in {"2025", "2026"} and row["comparison_tier"] != "PROPOSED"
]
assert len(recent) == 29
assert audit["status"] == "TERMINAL_ACCEPTED_FOR_REGISTRY_EXPANSION"
assert audit["registry_decisions"]["add"] == ["structmem", "hela-mem"]
assert audit["registry_decisions"]["numeric_rows_added"] == 0
assert audit["registry_decisions"]["source_reported_scores_imported"] == 0

with RESULTS.open(encoding="utf-8", newline="") as handle:
    result_rows = list(csv.DictReader(handle))
assert not result_rows, "registry revision must precede accepted WMA results"

print(
    json.dumps(
        {
            "status": "PASS",
            "registered_methods": len(v3_rows),
            "recent_2025_2026_methods": len(recent),
            "new_methods": ["structmem", "hela-mem"],
            "locally_reproduced_result_rows": len(result_rows),
        },
        sort_keys=True,
    )
)
