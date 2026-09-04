from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.causal_locomo_five_method_overlay import protocol_blocked_row, run_method
from scripts.causal_locomo_raw_run_writer import METHOD_ORDER, RawRunError, RawRunWriter


def view(qid: str) -> dict:
    return {
        "schema_version": "agentenhance.causal_locomo_inference_view.v1",
        "example_id": qid,
        "task_family": "factual_memory_qa",
        "past_sessions": [{"session_id": "s1", "timestamp": 1, "content": "history"}],
        "current_task": {"task_id": qid, "instruction": "alpha", "recipient_type": None, "domain": "qa"},
        "memory_bank": [{"memory_id": "m1", "content": "alpha", "timestamp": 1, "source_session_id": "s1"}],
    }


def answer(request: dict) -> dict:
    return {"text": "answer", "call": {"status": "ACCEPTED", "attempts": 1, "retry_count": 0}}


def embed(texts: list[str], seed: int) -> dict:
    return {"vectors": [[1.0, 0.0]], "call": {"status": "ACCEPTED", "attempts": 1, "retry_count": 0}}


def row_for(qid: str, method: str, seed: int) -> dict:
    current = view(qid)
    if method in {"cmi-reflection-memory", "cmi"}:
        return protocol_blocked_row(current, method_id=method, seed=seed)
    return run_method(current, method_id=method, seed=seed, answer=answer, embed=embed)


class RawRunWriterTests(unittest.TestCase):
    def test_complete_qid_major_surface_is_hashed_and_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "seed-0"
            writer = RawRunWriter(root, seed=0, qid_order=["e1", "e2"])
            for qid in ("e1", "e2"):
                for method in METHOD_ORDER:
                    writer.append(row_for(qid, method, 0))
            summary = writer.finalize()
            self.assertEqual(summary["rows"], 14)
            self.assertEqual(summary["accepted_rows"], 10)
            self.assertEqual(summary["protocol_blocked_rows"], 4)
            self.assertEqual(summary["method_execution_failed_rows"], 0)
            self.assertTrue((root / "TERMINAL_ACCEPTED").is_file())
            self.assertEqual(len((root / "predictions.jsonl").read_text().splitlines()), 14)
            self.assertEqual(len((root / "SHA256SUMS").read_text().splitlines()), 4)
            events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
            self.assertEqual(events[0]["event"], "STARTED")
            self.assertEqual(events[-1]["event"], "FINALIZED")

    def test_existing_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "seed-0"
            root.mkdir()
            with self.assertRaisesRegex(RawRunError, "already exists"):
                RawRunWriter(root, seed=0, qid_order=["e1"])

    def test_out_of_order_row_is_rejected_before_append(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "seed-0"
            writer = RawRunWriter(root, seed=0, qid_order=["e1"])
            with self.assertRaisesRegex(RawRunError, "order drift"):
                writer.append(row_for("e1", "cmi-full-history", 0))
            self.assertEqual((root / "predictions.jsonl").read_text(), "")

    def test_incomplete_finalize_is_rejected_and_root_retained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "seed-0"
            writer = RawRunWriter(root, seed=0, qid_order=["e1"])
            writer.append(row_for("e1", "cmi-no-memory", 0))
            with self.assertRaisesRegex(RawRunError, "incomplete"):
                writer.finalize()
            self.assertTrue(root.is_dir())
            self.assertFalse((root / "TERMINAL_ACCEPTED").exists())

    def test_protocol_blocked_row_cannot_hide_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "seed-0"
            writer = RawRunWriter(root, seed=0, qid_order=["e1"])
            writer.append(row_for("e1", "cmi-no-memory", 0))
            writer.append(row_for("e1", "cmi-full-history", 0))
            writer.append(row_for("e1", "cmi-vector-memory", 0))
            writer.append(row_for("e1", "cmi-summary-memory", 0))
            blocked = row_for("e1", "cmi-reflection-memory", 0)
            blocked["calls"].append({"status": "ACCEPTED", "attempts": 1, "retry_count": 0})
            with self.assertRaisesRegex(RawRunError, "protocol-blocked"):
                writer.append(blocked)


if __name__ == "__main__":
    unittest.main()

