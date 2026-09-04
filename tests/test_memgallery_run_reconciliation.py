from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reconcile_memgallery_method_run.py"
SPEC = importlib.util.spec_from_file_location("reconcile_memgallery_method_run", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def canonical(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def fixture() -> tuple[dict, list[dict], bytes, dict, list[dict]]:
    questions = [
        {"qid": "a:0", "question_sha256": "1" * 64},
        {"qid": "a:1", "question_sha256": "2" * 64},
    ]
    qid_bytes = b"a:0\na:1\n"
    question_index_bytes = b"".join(canonical(row) for row in questions)
    dataset = {
        "status": "TERMINAL_ACCEPTED",
        "dataset_semantic_identity_sha256": "d" * 64,
        "stable_identity": {
            "questions": 2,
            "qid_order_sha256": hashlib.sha256(qid_bytes).hexdigest(),
            "question_index_sha256": hashlib.sha256(question_index_bytes).hexdigest(),
        },
    }
    identity = {
        "schema_version": "agentenhance.memgallery_raw_run_identity.v1",
        "status": "TERMINAL_RAW_COMPLETE",
        "track_id": "memgallery-static-matched-v1",
        "method_id": "bm25",
        "seed": 0,
        "answer_model": MODULE.ANSWER_MODEL,
        "decoding": {"temperature": 0.0, "max_output_tokens": 128},
        "memory_budget": {"prospectively_frozen": True, "top_k": 10},
        "dataset_semantic_identity_sha256": "d" * 64,
        "qid_order_sha256": dataset["stable_identity"]["qid_order_sha256"],
        "questions_expected": 2,
        "official_values_used": False,
        "method_source": {"identity_frozen": True, "implementation_sha256": "a" * 64},
    }
    predictions = [
        {
            "schema_version": "agentenhance.memgallery_prediction.v1",
            "method_id": "bm25",
            "seed": 0,
            "qid": "a:0",
            "status": "ACCEPTED",
            "prediction": "answer",
            "error_type": None,
            "error": None,
            "retrieved_memory_ids": ["m1"],
            "retrieval_count": 1,
            "latency_seconds": 1.25,
        },
        {
            "schema_version": "agentenhance.memgallery_prediction.v1",
            "method_id": "bm25",
            "seed": 0,
            "qid": "a:1",
            "status": "FAILED",
            "prediction": "",
            "error_type": "HTTP_ERROR",
            "error": "request failed",
            "retrieved_memory_ids": [],
            "retrieval_count": 0,
            "latency_seconds": 2.0,
        },
    ]
    return dataset, questions, qid_bytes, identity, predictions


class MemGalleryRunReconciliationTests(unittest.TestCase):
    def test_complete_surface_keeps_failure_in_denominator(self) -> None:
        dataset, questions, qids, identity, predictions = fixture()
        summary, rows = MODULE.reconcile(dataset, questions, qids, identity, predictions)
        self.assertEqual(summary["prediction_rows"], 2)
        self.assertEqual(summary["accepted_rows"], 1)
        self.assertEqual(summary["failed_rows"], 1)
        self.assertEqual(summary["empty_answer_rows"], 1)
        self.assertEqual(summary["failure_types"], {"HTTP_ERROR": 1})
        self.assertEqual(rows.count(b"\n"), 2)
        self.assertFalse(summary["official_values_used"])
        self.assertFalse(summary["main_comparison_numerical_authorization"])

    def test_missing_or_reordered_qid_is_rejected(self) -> None:
        dataset, questions, qids, identity, predictions = fixture()
        predictions.reverse()
        with self.assertRaisesRegex(ValueError, "QIDs/order"):
            MODULE.reconcile(dataset, questions, qids, identity, predictions)

    def test_empty_accepted_answer_is_rejected(self) -> None:
        dataset, questions, qids, identity, predictions = fixture()
        predictions[0]["prediction"] = "  "
        with self.assertRaisesRegex(ValueError, "empty answer must be recorded as FAILED"):
            MODULE.reconcile(dataset, questions, qids, identity, predictions)

    def test_official_value_contamination_is_rejected(self) -> None:
        dataset, questions, qids, identity, predictions = fixture()
        identity["official_values_used"] = True
        with self.assertRaisesRegex(ValueError, "official values"):
            MODULE.reconcile(dataset, questions, qids, identity, predictions)

    def test_nonfinite_latency_is_rejected(self) -> None:
        dataset, questions, qids, identity, predictions = fixture()
        predictions[0]["latency_seconds"] = float("nan")
        with self.assertRaisesRegex(ValueError, "non-finite"):
            MODULE.reconcile(dataset, questions, qids, identity, predictions)


if __name__ == "__main__":
    unittest.main()
