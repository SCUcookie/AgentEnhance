from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "causal_locomo_inference_view", ROOT / "scripts" / "causal_locomo_inference_view.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def source_record() -> dict:
    return {
        "example_id": "example-1",
        "task_family": "temporal_memory_qa",
        "past_sessions": [
            {"session_id": "s1", "timestamp": 1, "content": "Earlier dialogue."}
        ],
        "current_task": {
            "task_id": "q1",
            "instruction": "What changed?",
            "recipient_type": None,
            "domain": "conversation",
        },
        "memory_bank": [
            {
                "memory_id": "m1",
                "content": "Visible evidence.",
                "timestamp": 1,
                "source_session_id": "s1",
                "label": "useful",
                "type": "repaired_gold_memory",
                "scope": "gold_evidence",
                "expected_effect": "must improve the answer",
                "causal_role": "gold",
                "synthetic": False,
                "derivation": {"uses_gold_answer": True},
            }
        ],
        "gold_memory_ids": ["m1"],
        "bad_memory_ids": [],
        "context_dependent_memory_ids": [],
        "gold_behavior": "The expected answer.",
        "scoring_criteria": {"expected_answer": "secret"},
        "intervention_tests": [{"gold": True}],
        "metadata": {"num_gold_memories": 1},
        "quality_status": "accepted",
    }


class InferenceViewTests(unittest.TestCase):
    def test_removes_all_evaluator_only_fields(self) -> None:
        view = MODULE.build_inference_view(source_record())
        self.assertEqual(
            set(view),
            {"schema_version", "example_id", "task_family", "past_sessions", "current_task", "memory_bank"},
        )
        self.assertEqual(
            set(view["memory_bank"][0]),
            {"memory_id", "content", "timestamp", "source_session_id"},
        )
        serialized = repr(view)
        for secret in ("useful", "repaired_gold_memory", "gold_evidence", "expected answer", "secret"):
            self.assertNotIn(secret, serialized)

    def test_does_not_mutate_authoritative_record(self) -> None:
        record = source_record()
        before = copy.deepcopy(record)
        MODULE.build_inference_view(record)
        self.assertEqual(record, before)

    def test_rejects_duplicate_or_unordered_units(self) -> None:
        duplicate = source_record()
        duplicate["memory_bank"].append(copy.deepcopy(duplicate["memory_bank"][0]))
        with self.assertRaisesRegex(MODULE.InferenceViewError, "duplicate memory_id"):
            MODULE.build_inference_view(duplicate)

        unordered = source_record()
        unordered["past_sessions"] = [
            {"session_id": "s2", "timestamp": 2, "content": "Second."},
            {"session_id": "s1", "timestamp": 1, "content": "First."},
        ]
        with self.assertRaisesRegex(MODULE.InferenceViewError, "chronological"):
            MODULE.build_inference_view(unordered)

    def test_blind_assertion_rejects_reintroduced_labels(self) -> None:
        view = MODULE.build_inference_view(source_record())
        view["memory_bank"][0]["label"] = "useful"
        with self.assertRaisesRegex(MODULE.InferenceViewError, "evaluation-only memory"):
            MODULE.assert_blind_view(view)

    def test_hash_is_key_order_invariant(self) -> None:
        view = MODULE.build_inference_view(source_record())
        reversed_view = dict(reversed(list(view.items())))
        self.assertEqual(MODULE.canonical_sha256(view), MODULE.canonical_sha256(reversed_view))


if __name__ == "__main__":
    unittest.main()

