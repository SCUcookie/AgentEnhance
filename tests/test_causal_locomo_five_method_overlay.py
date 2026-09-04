from __future__ import annotations

import unittest

from scripts.causal_locomo_five_method_overlay import OverlayError, protocol_blocked_row, run_method


def blind_view(memory_count: int = 6) -> dict:
    memories = []
    for index in range(memory_count):
        text = "alpha target evidence" if index == 4 else f"unrelated memory {index}"
        memories.append(
            {
                "memory_id": f"m{index}",
                "content": text,
                "timestamp": index,
                "source_session_id": "s1",
            }
        )
    return {
        "schema_version": "agentenhance.causal_locomo_inference_view.v1",
        "example_id": "e1",
        "task_family": "factual_memory_qa",
        "past_sessions": [{"session_id": "s1", "timestamp": 0, "content": "history text"}],
        "current_task": {
            "task_id": "q1",
            "instruction": "find alpha target",
            "recipient_type": None,
            "domain": "conversation",
        },
        "memory_bank": memories,
    }


class Calls:
    def __init__(self) -> None:
        self.answers: list[dict] = []
        self.embeddings: list[list[str]] = []

    def answer(self, request: dict) -> dict:
        self.answers.append(request)
        return {
            "text": "accepted answer",
            "call": {"status": "ACCEPTED", "attempts": 1, "retry_count": 0},
        }

    def embed(self, texts: list[str], seed: int) -> dict:
        self.embeddings.append(list(texts))
        text = texts[0]
        vector = [1.0, 0.0] if "alpha" in text else [0.0, 1.0]
        return {
            "vectors": [vector],
            "call": {"status": "ACCEPTED", "attempts": 1, "retry_count": 0, "seed": seed},
        }


class FiveMethodOverlayTests(unittest.TestCase):
    def test_no_memory_and_full_history_use_distinct_blind_prompts(self) -> None:
        calls = Calls()
        no_memory = run_method(blind_view(), method_id="cmi-no-memory", seed=0, answer=calls.answer)
        full_history = run_method(blind_view(), method_id="cmi-full-history", seed=0, answer=calls.answer)
        self.assertEqual(no_memory["selected_memory_ids"], [])
        self.assertEqual(full_history["selected_memory_ids"], [f"m{i}" for i in range(6)])
        self.assertIn("Current task", calls.answers[0]["messages"][0]["content"])
        self.assertNotIn("history text", calls.answers[0]["messages"][0]["content"])
        self.assertIn("history text", calls.answers[1]["messages"][0]["content"])

    def test_vector_memory_calls_every_embedding_once_and_selects_target(self) -> None:
        calls = Calls()
        row = run_method(
            blind_view(), method_id="cmi-vector-memory", seed=1, answer=calls.answer, embed=calls.embed
        )
        self.assertEqual(row["status"], "ACCEPTED")
        self.assertEqual(len(calls.embeddings), 7)
        self.assertEqual(row["selected_memory_ids"][0], "m4")
        self.assertEqual(len(row["selected_memory_ids"]), 5)
        self.assertEqual(len(row["calls"]), 8)

    def test_embedding_failure_is_retained_without_answer_fallback(self) -> None:
        calls = Calls()

        def broken_embed(texts: list[str], seed: int) -> dict:
            raise TimeoutError("frozen endpoint timed out")

        row = run_method(
            blind_view(), method_id="cmi-vector-memory", seed=2, answer=calls.answer, embed=broken_embed
        )
        self.assertEqual(row["status"], "FAILED")
        self.assertEqual(row["error_type"], "TimeoutError")
        self.assertEqual(calls.answers, [])
        self.assertEqual(row["response"], "")

    def test_summary_uses_only_first_eight_visible_contents(self) -> None:
        calls = Calls()
        view = blind_view(10)
        row = run_method(view, method_id="cmi-summary-memory", seed=0, answer=calls.answer)
        prompt = calls.answers[0]["messages"][0]["content"]
        self.assertEqual(row["selected_memory_ids"], [f"m{i}" for i in range(10)])
        self.assertIn("unrelated memory 7", prompt)
        self.assertNotIn("unrelated memory 8", prompt)

    def test_graph_uses_content_only_and_stable_source_order_ties(self) -> None:
        calls = Calls()
        row = run_method(blind_view(), method_id="cmi-graph-memory", seed=0, answer=calls.answer)
        self.assertEqual(row["selected_memory_ids"][0], "m4")
        self.assertEqual(row["selected_memory_ids"][1:], ["m0", "m1", "m2", "m3"])

    def test_blocked_methods_cannot_be_executed(self) -> None:
        calls = Calls()
        for method in ("cmi-reflection-memory", "cmi"):
            with self.assertRaisesRegex(OverlayError, "protocol-blocked"):
                run_method(blind_view(), method_id=method, seed=0, answer=calls.answer)
        self.assertEqual(calls.answers, [])

    def test_blocked_methods_have_explicit_denominator_rows(self) -> None:
        for method in ("cmi-reflection-memory", "cmi"):
            row = protocol_blocked_row(blind_view(), method_id=method, seed=2)
            self.assertEqual(row["status"], "FAILED")
            self.assertEqual(row["failure_kind"], "PROTOCOL_BLOCKED")
            self.assertEqual(row["error_type"], "ProtocolBlockedGoldLeak")
            self.assertEqual(row["calls"], [])

    def test_answer_failure_preserves_one_denominator_row(self) -> None:
        def failed_answer(request: dict) -> dict:
            return {
                "text": "",
                "call": {"status": "FAILED", "attempts": 1, "retry_count": 0},
            }

        row = run_method(blind_view(), method_id="cmi-no-memory", seed=0, answer=failed_answer)
        self.assertEqual(row["status"], "FAILED")
        self.assertEqual(row["example_id"], "e1")
        self.assertEqual(row["method_id"], "cmi-no-memory")


if __name__ == "__main__":
    unittest.main()
