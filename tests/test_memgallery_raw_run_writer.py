from __future__ import annotations

import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "memgallery_raw_run_writer.py"
SPEC = importlib.util.spec_from_file_location("memgallery_raw_run_writer", MODULE_PATH)
assert SPEC and SPEC.loader
writer_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(writer_module)

RECONCILE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "reconcile_memgallery_method_run.py"
RECONCILE_SPEC = importlib.util.spec_from_file_location("reconcile_memgallery_method_run", RECONCILE_PATH)
assert RECONCILE_SPEC and RECONCILE_SPEC.loader
reconcile_module = importlib.util.module_from_spec(RECONCILE_SPEC)
RECONCILE_SPEC.loader.exec_module(reconcile_module)


def prediction(qid: str, status: str = "ACCEPTED") -> dict:
    failed = status == "FAILED"
    return {
        "schema_version": "agentenhance.memgallery_prediction.v1",
        "method_id": "bm25",
        "seed": 0,
        "qid": qid,
        "status": status,
        "prediction": "" if failed else "answer",
        "error_type": "TimeoutError" if failed else None,
        "error": "timeout" if failed else None,
        "retrieved_memory_ids": [],
        "retrieval_count": 0,
        "latency_seconds": 0.1,
    }


def scenario(qids: list[str], statuses: list[str] | None = None) -> dict:
    statuses = statuses or ["ACCEPTED"] * len(qids)
    predictions = [prediction(qid, status) for qid, status in zip(qids, statuses)]
    return {
        "status": "TERMINAL_SCENARIO_COMPLETE",
        "scenario": "s",
        "method_id": "bm25",
        "seed": 0,
        "questions": len(qids),
        "predictions": predictions,
        "retrieval_traces": [
            {"qid": qid, "method_id": "bm25", "seed": 0, "status": status}
            for qid, status in zip(qids, statuses)
        ],
        "call_records": [
            {
                "qid": qid,
                "method_id": "bm25",
                "seed": 0,
                "call_category": "final_answer",
                "status": status,
                "attempts": 1,
                "retry_count": 0,
            }
            for qid, status in zip(qids, statuses)
        ],
    }


class MemGalleryRawRunWriterTests(unittest.TestCase):
    def make_writer(self, scope: Path, name: str = "run"):
        return writer_module.RawRunWriter(
            scope / name,
            allowed_run_scopes=[scope],
            method_id="bm25",
            seed=0,
            expected_qids=["s:0", "s:1"],
            dataset_semantic_identity_sha256="1" * 64,
            qid_order_sha256="2" * 64,
            question_index_sha256="3" * 64,
            method_source={"identity_frozen": True, "implementation_sha256": "4" * 64},
            memory_budget={"prospectively_frozen": True, "top_k": 10},
        )

    def test_complete_run_is_reconciliation_compatible_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            writer = self.make_writer(scope)
            writer.append_scenario(scenario(["s:0"], ["FAILED"]))
            writer.append_scenario(scenario(["s:1"]))
            identity = writer.finalize()
            self.assertEqual(identity["status"], "TERMINAL_RAW_COMPLETE")
            self.assertTrue((writer.root / "TERMINAL_RAW_COMPLETE").is_file())
            self.assertFalse((writer.root / "TERMINAL_REJECTED").exists())
            summary = json.loads((writer.root / "raw-run-summary.json").read_text())
            self.assertEqual(summary["prediction_rows"], 2)
            self.assertEqual(summary["failed_prediction_rows"], 1)
            self.assertEqual(summary["scores_observed"], 0)
            self.assertEqual(len((writer.root / "EVIDENCE_SHA256SUMS").read_text().splitlines()), 7)

    def test_existing_root_collision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            (scope / "run").mkdir()
            with self.assertRaisesRegex(ValueError, "existing output root"):
                self.make_writer(scope)

    def test_out_of_order_qid_is_rejected_before_append(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            writer = self.make_writer(Path(temporary).resolve())
            with self.assertRaisesRegex(ValueError, "frozen order"):
                writer.append_scenario(scenario(["s:1"]))
            self.assertEqual((writer.root / "raw-predictions.jsonl").read_bytes(), b"")

    def test_incomplete_finalize_is_rejected_then_failure_root_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            writer = self.make_writer(Path(temporary).resolve())
            writer.append_scenario(scenario(["s:0"]))
            with self.assertRaisesRegex(ValueError, "full frozen QID") as caught:
                writer.finalize()
            failure = writer.reject(caught.exception)
            self.assertEqual(failure["rows_retained"], 1)
            self.assertFalse(failure["same_root_retry_allowed"])
            self.assertTrue((writer.root / "TERMINAL_REJECTED").is_file())
            self.assertTrue((writer.root / "raw-predictions.jsonl").read_text())

    def test_call_retry_or_identity_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            writer = self.make_writer(Path(temporary).resolve())
            result = scenario(["s:0"])
            result["call_records"][0]["retry_count"] = 1
            with self.assertRaisesRegex(ValueError, "retry drift"):
                writer.append_scenario(result)

    def test_terminal_output_passes_the_existing_reconciliation_core(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            question_rows = [{"qid": "s:0"}, {"qid": "s:1"}]
            qid_bytes = b"s:0\ns:1\n"
            question_bytes = b"".join(reconcile_module.canonical_json_bytes(row) for row in question_rows)
            qid_sha = hashlib.sha256(qid_bytes).hexdigest()
            question_sha = hashlib.sha256(question_bytes).hexdigest()
            dataset_identity = "1" * 64
            writer = writer_module.RawRunWriter(
                scope / "run",
                allowed_run_scopes=[scope],
                method_id="bm25",
                seed=0,
                expected_qids=["s:0", "s:1"],
                dataset_semantic_identity_sha256=dataset_identity,
                qid_order_sha256=qid_sha,
                question_index_sha256=question_sha,
                method_source={"identity_frozen": True, "implementation_sha256": "4" * 64},
                memory_budget={"prospectively_frozen": True, "top_k": 10},
            )
            writer.append_scenario(scenario(["s:0", "s:1"]))
            identity = writer.finalize()
            predictions = reconcile_module.read_jsonl(writer.root / "raw-predictions.jsonl")
            dataset = {
                "status": "TERMINAL_ACCEPTED",
                "dataset_semantic_identity_sha256": dataset_identity,
                "stable_identity": {
                    "questions": 2,
                    "qid_order_sha256": qid_sha,
                    "question_index_sha256": question_sha,
                },
            }
            summary, reconciled = reconcile_module.reconcile(
                dataset, question_rows, qid_bytes, identity, predictions
            )
            self.assertEqual(summary["status"], "TERMINAL_ACCEPTED")
            self.assertEqual(summary["prediction_rows"], 2)
            self.assertEqual(len(reconciled.splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
