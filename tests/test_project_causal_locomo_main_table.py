from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.project_causal_locomo_main_table import (
    BLOCKED_METHODS,
    COST_METRICS,
    METHOD_ORDER,
    QUALITY_METRICS,
    ProjectionError,
    load_evaluation_root,
    load_template,
    project_summary,
    write_projection,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "comparisons" / "causal-locomo-main-table-template.v1.csv"
SHA = "a" * 64


def summary() -> dict:
    rows = []
    for method in sorted(METHOD_ORDER):
        blocked = method in BLOCKED_METHODS
        rows.append({
            "method_id": method,
            "registered_rows": 261,
            "accepted_rows": 0 if blocked else 261,
            "failed_rows": 261 if blocked else 0,
            "protocol_blocked_rows": 261 if blocked else 0,
            "comparison_status": "PROTOCOL_BLOCKED" if blocked else "ELIGIBLE",
            "metrics": None if blocked else {metric: 0.5 for metric in QUALITY_METRICS},
            "cost_metrics": {metric: 0.0 if blocked else 2.0 for metric in COST_METRICS},
        })
    by_family = [{**row, "task_family": "factual_memory_qa"} for row in rows]
    return {
        "schema_version": "agentenhance.causal_locomo_evaluation_summary.v1",
        "mode": "real",
        "registered_rows": 1827,
        "accepted_rows": 1305,
        "failed_rows": 522,
        "protocol_blocked_rows": 522,
        "failure_imputation": {"higher_is_better": 0.0, "lower_is_better": 1.0},
        "by_method": rows,
        "by_method_and_task_family": by_family,
    }


def write_evaluation_root(root: Path) -> str:
    root.mkdir()
    qids = [f"e{index:03d}" for index in range(87)]
    qid_hash = hashlib.sha256(("\n".join(qids) + "\n").encode()).hexdigest()
    score_rows = []
    for seed in (0, 1, 2):
        for qid in qids:
            for method in METHOD_ORDER:
                blocked = method in BLOCKED_METHODS
                score_rows.append({
                    "schema_version": "agentenhance.causal_locomo_score.v1",
                    "example_id": qid,
                    "task_family": "factual_memory_qa",
                    "method_id": method,
                    "seed": seed,
                    "prediction_status": "FAILED" if blocked else "ACCEPTED",
                    "failure_kind": "PROTOCOL_BLOCKED" if blocked else None,
                    "comparison_status": "PROTOCOL_BLOCKED" if blocked else "ELIGIBLE_ACCEPTED",
                    "metrics": None if blocked else {metric: 0.5 for metric in QUALITY_METRICS},
                    "cost_metrics": {metric: 0.0 if blocked else 2.0 for metric in COST_METRICS},
                })
    audit = {
        "schema_version": "agentenhance.causal_locomo_evaluation_audit.v1",
        "qid_order_sha256": qid_hash,
        "raw_rows": 1827,
        "score_rows": 1827,
        "missing_rows": 0,
        "dropped_failed_rows": 0,
        "official_values_used": False,
    }
    payloads = {
        "audit.json": json.dumps(audit, sort_keys=True, separators=(",", ":")) + "\n",
        "scores.jsonl": "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in score_rows),
        "summary.json": json.dumps(summary(), sort_keys=True, separators=(",", ":")) + "\n",
    }
    for name, payload in payloads.items():
        (root / name).write_text(payload, encoding="utf-8")
    inventory = "".join(
        f"{hashlib.sha256((root / name).read_bytes()).hexdigest()}  {name}\n" for name in sorted(payloads)
    )
    (root / "SHA256SUMS").write_text(inventory, encoding="utf-8")
    (root / "TERMINAL_ACCEPTED").touch()
    return qid_hash


class CausalLocomoProjectionTests(unittest.TestCase):
    def test_complete_summary_projects_five_numeric_rows_and_keeps_three_rows_blank(self) -> None:
        fields, template = load_template(TEMPLATE)
        rows = project_summary(summary(), template, run_id="local-real-v1", evidence_archive_sha256=SHA)
        by_method = {row["method_id"]: row for row in rows}
        self.assertEqual(len(fields), 32)
        self.assertEqual(by_method["cmi-no-memory"]["comparison_status"], "ACCEPTED_LOCAL_MATCHED")
        self.assertEqual(by_method["cmi-no-memory"]["task_score"], "0.5")
        self.assertTrue(all(by_method[method]["task_score"] == "" for method in BLOCKED_METHODS))
        self.assertEqual(by_method["agentenhance-ceu"]["task_score"], "")
        self.assertEqual(by_method["agentenhance-ceu"]["comparison_status"], "LOCKED_UNTIL_BASELINE_GATE")

    def test_partial_or_synthetic_summary_is_rejected(self) -> None:
        _, template = load_template(TEMPLATE)
        candidate = summary()
        candidate["mode"] = "synthetic"
        with self.assertRaisesRegex(ProjectionError, "mode"):
            project_summary(candidate, template, run_id="run", evidence_archive_sha256=SHA)
        candidate = summary()
        candidate["by_method"].pop()
        with self.assertRaisesRegex(ProjectionError, "method surface"):
            project_summary(candidate, template, run_id="run", evidence_archive_sha256=SHA)

    def test_nonfinite_or_protocol_blocker_numeric_value_is_rejected(self) -> None:
        _, template = load_template(TEMPLATE)
        candidate = summary()
        next(row for row in candidate["by_method"] if row["method_id"] == "cmi-no-memory")["metrics"]["task_score"] = float("nan")
        with self.assertRaisesRegex(ProjectionError, "range"):
            project_summary(candidate, template, run_id="run", evidence_archive_sha256=SHA)
        candidate = summary()
        next(row for row in candidate["by_method"] if row["method_id"] == "cmi")["metrics"] = {metric: 0.0 for metric in QUALITY_METRICS}
        with self.assertRaisesRegex(ProjectionError, "blocker"):
            project_summary(candidate, template, run_id="run", evidence_archive_sha256=SHA)

    def test_projection_root_is_fresh_hashed_and_contains_no_agentenhance_values(self) -> None:
        fields, template = load_template(TEMPLATE)
        rows = project_summary(summary(), template, run_id="local-real-v1", evidence_archive_sha256=SHA)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "projection"
            manifest = write_projection(
                root, fields=fields, rows=rows, template_sha256=SHA,
                evaluation_inventory_sha256="b" * 64, evidence_archive_sha256=SHA,
            )
            self.assertEqual(manifest["populated_local_metric_cells"], 105)
            self.assertFalse(manifest["official_values_used"])
            self.assertTrue((root / "TERMINAL_ACCEPTED").is_file())
            with (root / "causal-locomo-main-table.csv").open(newline="", encoding="utf-8") as handle:
                projected = {row["method_id"]: row for row in csv.DictReader(handle)}
            self.assertEqual(projected["agentenhance-ceu"]["task_score"], "")
            with self.assertRaisesRegex(ProjectionError, "fresh"):
                write_projection(
                    root, fields=fields, rows=rows, template_sha256=SHA,
                    evaluation_inventory_sha256="b" * 64, evidence_archive_sha256=SHA,
                )

    def test_terminal_evaluation_root_is_independently_reconciled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "evaluation"
            qid_hash = write_evaluation_root(root)
            loaded, inventory_sha = load_evaluation_root(root, expected_qid_order_sha256=qid_hash)
            self.assertEqual(loaded["registered_rows"], 1827)
            self.assertEqual(len(inventory_sha), 64)
            with (root / "scores.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("{}\n")
            with self.assertRaisesRegex(ProjectionError, "inventory mismatch"):
                load_evaluation_root(root, expected_qid_order_sha256=qid_hash)


if __name__ == "__main__":
    unittest.main()
