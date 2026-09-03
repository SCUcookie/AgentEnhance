#!/usr/bin/env python3
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "comparisons" / "baseline-evidence-policy.v2.json"
REGISTER = ROOT / "comparisons" / "baseline-register.v2.csv"
RESULTS = ROOT / "comparisons" / "reproduced-results.v1.csv"
RETENTION = ROOT / "comparisons" / "model-retention-policy.v1.json"


def load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


policy = load_json(POLICY)
retention = load_json(RETENTION)
assert policy["status"] == "FROZEN"
assert "locally" in policy["primary_evidence_rule"]
assert "supporting a best or SOTA claim" in policy["source_reported_policy"]["prohibited_uses"]
assert len(policy["comparison_tracks"]) == 3
assert retention["status"] == "FROZEN"
assert retention["cleanup_preconditions"]
assert any("pre-existing" in item for item in retention["never_delete_by_this_policy"])

with REGISTER.open(newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))
assert len(rows) >= 30, len(rows)
assert len({row["method_id"] for row in rows}) == len(rows)
recent = [row for row in rows if row["year"] in {"2025", "2026"} and row["comparison_tier"] != "PROPOSED"]
assert len(recent) >= 20, len(recent)
assert sum(row["comparison_tier"] == "A" for row in rows) >= 15

required_result_fields = policy["result_admission"]["required_fields"]
with RESULTS.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    assert reader.fieldnames is not None
    missing = sorted(set(required_result_fields) - set(reader.fieldnames))
    assert not missing, missing
    result_rows = list(reader)
for row in result_rows:
    assert row["status"] == "ACCEPTED"
    assert int(row["n_observed"]) + int(row["n_failed"]) == int(row["n_expected"])
    assert row["artifact_sha256"]

print(json.dumps({
    "status": "PASS",
    "registered_methods": len(rows),
    "recent_2025_2026_methods": len(recent),
    "locally_reproduced_result_rows": len(result_rows),
}, sort_keys=True))
