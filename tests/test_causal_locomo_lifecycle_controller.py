from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.causal_locomo_lifecycle_controller import LifecycleError, run_lifecycle


def record(qid: str, answer_marker: str = "secret-gold") -> dict:
    return {
        "example_id": qid,
        "task_family": "factual_memory_qa",
        "past_sessions": [{"session_id": "s1", "timestamp": 1, "content": "visible history"}],
        "current_task": {"task_id": qid, "instruction": "find alpha", "recipient_type": None, "domain": "qa"},
        "memory_bank": [
            {
                "memory_id": "m1",
                "content": "visible alpha evidence",
                "timestamp": 1,
                "source_session_id": "s1",
                "label": "useful",
                "type": "repaired_gold_memory",
                "scope": "gold_evidence",
                "expected_effect": answer_marker,
                "causal_role": "gold",
                "derivation": {"uses_gold_answer": True},
                "synthetic": False,
            }
        ],
        "gold_memory_ids": ["m1"],
        "bad_memory_ids": [],
        "context_dependent_memory_ids": [],
        "gold_behavior": answer_marker,
        "scoring_criteria": {"expected_answer": answer_marker},
        "intervention_tests": [{"answer": answer_marker}],
        "metadata": {"answer": answer_marker},
        "quality_status": "accepted",
    }


class MockEndpoints:
    def __init__(self, fail_prompts: bool = False):
        self.prompts: list[str] = []
        self.fail_prompts = fail_prompts

    def answer(self, request: dict) -> dict:
        prompt = request["messages"][0]["content"]
        self.prompts.append(prompt)
        if self.fail_prompts and "using only memories" in prompt:
            raise TimeoutError("synthetic answer failure")
        return {"text": "synthetic answer", "call": {"status": "ACCEPTED", "attempts": 1, "retry_count": 0}}

    def embed(self, texts: list[str], seed: int) -> dict:
        return {"vectors": [[1.0, float(seed + 1)]], "call": {"status": "ACCEPTED", "attempts": 1, "retry_count": 0}}


class LifecycleControllerTests(unittest.TestCase):
    def test_three_seed_complete_surface_and_no_gold_prompt_leak(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "lifecycle"
            endpoints = MockEndpoints()
            summary = run_lifecycle(
                root, mode="synthetic", records=[record("e1"), record("e2")],
                answer=endpoints.answer, embed=endpoints.embed,
            )
            self.assertEqual(summary["rows"], 42)
            self.assertEqual(summary["accepted_rows"], 30)
            self.assertEqual(summary["protocol_blocked_rows"], 12)
            self.assertEqual(summary["method_execution_failed_rows"], 0)
            self.assertTrue((root / "TERMINAL_ACCEPTED").is_file())
            self.assertEqual(len((root / "SHA256SUMS").read_text().splitlines()), 13)
            self.assertTrue(all("secret-gold" not in prompt for prompt in endpoints.prompts))
            for seed in range(3):
                rows = [json.loads(line) for line in (root / f"seed-{seed}" / "predictions.jsonl").read_text().splitlines()]
                self.assertEqual(len(rows), 14)

    def test_real_mode_is_rejected_before_root_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "real"
            endpoints = MockEndpoints()
            with self.assertRaisesRegex(LifecycleError, "not implemented"):
                run_lifecycle(
                    root, mode="real", records=[record("e1")],
                    answer=endpoints.answer, embed=endpoints.embed,
                )
            self.assertFalse(root.exists())
            self.assertEqual(endpoints.prompts, [])

    def test_duplicate_qid_is_rejected_before_root_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "duplicate"
            endpoints = MockEndpoints()
            with self.assertRaisesRegex(LifecycleError, "unique"):
                run_lifecycle(
                    root, mode="synthetic", records=[record("e1"), record("e1")],
                    answer=endpoints.answer, embed=endpoints.embed,
                )
            self.assertFalse(root.exists())

    def test_existing_root_is_rejected_without_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "existing"
            root.mkdir()
            endpoints = MockEndpoints()
            with self.assertRaisesRegex(LifecycleError, "already exists"):
                run_lifecycle(
                    root, mode="synthetic", records=[record("e1")],
                    answer=endpoints.answer, embed=endpoints.embed,
                )
            self.assertEqual(endpoints.prompts, [])

    def test_method_failures_remain_in_complete_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "failures"
            endpoints = MockEndpoints(fail_prompts=True)
            summary = run_lifecycle(
                root, mode="synthetic", records=[record("e1")],
                answer=endpoints.answer, embed=endpoints.embed,
            )
            self.assertEqual(summary["rows"], 21)
            self.assertEqual(summary["protocol_blocked_rows"], 6)
            self.assertEqual(summary["method_execution_failed_rows"], 9)
            self.assertEqual(summary["accepted_rows"], 6)
            self.assertTrue((root / "TERMINAL_ACCEPTED").is_file())


if __name__ == "__main__":
    unittest.main()

