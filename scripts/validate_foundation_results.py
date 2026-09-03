#!/usr/bin/env python3
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "comparisons" / "cmi-r2-full-recovery1-audit.v1.json"
RESULTS = ROOT / "comparisons" / "foundation-results.v1.csv"
MAIN_RESULTS = ROOT / "comparisons" / "reproduced-results.v1.csv"

audit = json.loads(AUDIT.read_text(encoding="utf-8"))
assert audit["outcome"] == "ACCEPT"
assert audit["main_comparison_eligible"] is False
assert audit["model_files_downloaded"] is False
assert audit["model_files_deleted"] is False

with RESULTS.open(newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))
expected = {
    "cmi", "cmi-full-history", "cmi-graph-memory", "cmi-no-memory",
    "cmi-reflection-memory", "cmi-summary-memory", "cmi-vector-memory",
}
assert len(rows) == 7
assert {row["method_id"] for row in rows} == expected
assert len({(row["run_id"], row["method_id"]) for row in rows}) == 7
numeric = [
    "task_score", "task_success_rate", "useful_memory_precision",
    "useful_memory_recall", "useful_memory_f1",
    "harmful_memory_rejection_rate", "irrelevant_memory_rejection_rate",
    "outdated_memory_rejection_rate", "poisoned_memory_adoption_rate",
    "context_dependent_memory_accuracy", "num_retrieved_memories",
    "num_selected_memories", "total_tokens", "cost_usd",
]
for row in rows:
    assert row["status"] == "ACCEPTED_DEVELOPMENT"
    assert row["evidence_role"] == "development-foundation"
    assert row["main_comparison_eligible"] == "false"
    assert int(row["attempts"]) == 2
    assert int(row["examples_per_attempt"]) == 87
    assert int(row["rows_per_attempt"]) == 609
    assert row["archive_sha256"] == audit["archive"]["sha256"]
    assert row["score_records_sha256"] == audit["score_records_sha256"]
    assert float(row["cost_usd"]) == 0.0
    assert all(math.isfinite(float(row[field])) for field in numeric)

with MAIN_RESULTS.open(newline="", encoding="utf-8") as handle:
    assert list(csv.DictReader(handle)) == [], "development values leaked into main results"

archive = ROOT / audit["archive"]["local_path"]
archive_local = archive.exists()
if archive_local:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert digest == audit["archive"]["sha256"]

print(json.dumps({
    "status": "PASS",
    "foundation_rows": len(rows),
    "main_result_rows": 0,
    "archive_local_and_verified": archive_local,
}, sort_keys=True))
