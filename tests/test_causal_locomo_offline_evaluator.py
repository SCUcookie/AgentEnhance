from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.causal_locomo_lifecycle_controller import run_lifecycle
from scripts.causal_locomo_offline_evaluator import EvaluationError, evaluate_lifecycle


def record(qid: str, task_family: str = "factual_memory_qa") -> dict:
    return {
        "example_id": qid,
        "task_family": task_family,
        "past_sessions": [{"session_id": "s1", "timestamp": 1, "content": "alpha history"}],
        "current_task": {"task_id": qid, "instruction": "answer alpha", "recipient_type": None, "domain": "qa"},
        "memory_bank": [
            {"memory_id": "good", "content": "alpha", "timestamp": 1, "source_session_id": "s1", "label": "useful", "type": "fact"},
            {"memory_id": "bad", "content": "poison", "timestamp": 2, "source_session_id": "s1", "label": "harmful", "type": "poisoned"},
        ],
        "gold_memory_ids": ["good"],
        "bad_memory_ids": ["bad"],
        "context_dependent_memory_ids": [],
        "scoring_criteria": {"must_include": ["alpha"], "must_not_include": ["poison"], "max_words": 5},
    }


class Endpoints:
    def __init__(self, fail: bool = False):
        self.fail = fail

    def answer(self, request: dict) -> dict:
        if self.fail and "using only memories" in request["messages"][0]["content"]:
            raise TimeoutError("synthetic timeout")
        return {
            "text": "alpha",
            "call": {
                "status": "ACCEPTED", "attempts": 1, "retry_count": 0,
                "prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11, "wall_seconds": 0.25,
            },
        }

    def embed(self, texts: list[str], seed: int) -> dict:
        return {
            "vectors": [[1.0, float(seed + 1)]],
            "call": {
                "status": "ACCEPTED", "attempts": 1, "retry_count": 0,
                "prompt_tokens": 2, "completion_tokens": 0, "total_tokens": 2, "wall_seconds": 0.1,
            },
        }


class OfflineEvaluatorTests(unittest.TestCase):
    def _lifecycle(self, parent: Path, records: list[dict], fail: bool = False) -> Path:
        root = parent / "raw"
        endpoints = Endpoints(fail=fail)
        run_lifecycle(root, mode="synthetic", records=records, answer=endpoints.answer, embed=endpoints.embed)
        return root

    def test_complete_scores_keep_blocked_cells_null_and_emit_rich_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            records = [record("e1"), record("e2", "temporal_memory_qa")]
            raw = self._lifecycle(parent, records)
            summary = evaluate_lifecycle(parent / "evaluation", mode="synthetic", raw_root=raw, records=records)
            self.assertEqual(summary["registered_rows"], 42)
            self.assertEqual(summary["protocol_blocked_rows"], 12)
            self.assertEqual(len(summary["by_method"]), 7)
            by_method = {row["method_id"]: row for row in summary["by_method"]}
            self.assertIsNone(by_method["cmi"]["metrics"])
            self.assertEqual(by_method["cmi"]["comparison_status"], "PROTOCOL_BLOCKED")
            self.assertEqual(by_method["cmi-no-memory"]["metrics"]["task_score"], 1.0)
            self.assertIn("total_tokens", by_method["cmi-vector-memory"]["cost_metrics"])
            self.assertEqual(len(summary["by_method_and_task_family"]), 14)
            self.assertTrue((parent / "evaluation" / "TERMINAL_ACCEPTED").is_file())
            rows = [json.loads(line) for line in (parent / "evaluation" / "scores.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 42)

    def test_method_execution_failures_receive_conservative_values_and_stay_in_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            records = [record("e1")]
            raw = self._lifecycle(parent, records, fail=True)
            summary = evaluate_lifecycle(parent / "evaluation", mode="synthetic", raw_root=raw, records=records)
            by_method = {row["method_id"]: row for row in summary["by_method"]}
            failed = by_method["cmi-vector-memory"]
            self.assertEqual(failed["registered_rows"], 3)
            self.assertEqual(failed["failed_rows"], 3)
            self.assertEqual(failed["metrics"]["task_score"], 0.0)
            self.assertEqual(failed["metrics"]["harmful_memory_rejection_rate"], 0.0)
            self.assertEqual(failed["metrics"]["poisoned_memory_adoption_rate"], 1.0)

    def test_tampered_raw_member_is_rejected_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            records = [record("e1")]
            raw = self._lifecycle(parent, records)
            with (raw / "seed-0" / "predictions.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("{}\n")
            output = parent / "evaluation"
            with self.assertRaisesRegex(EvaluationError, "inventory member mismatch"):
                evaluate_lifecycle(output, mode="synthetic", raw_root=raw, records=records)
            self.assertFalse(output.exists())

    def test_gold_identity_drift_and_real_mode_are_rejected_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            records = [record("e1")]
            raw = self._lifecycle(parent, records)
            output = parent / "evaluation"
            with self.assertRaisesRegex(EvaluationError, "real evaluation mode"):
                evaluate_lifecycle(output, mode="real", raw_root=raw, records=records)
            self.assertFalse(output.exists())
            with self.assertRaisesRegex(EvaluationError, "identity drift"):
                evaluate_lifecycle(output, mode="synthetic", raw_root=raw, records=[record("different")])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
