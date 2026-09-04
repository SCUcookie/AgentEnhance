from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "memgallery_control_runner.py"
SPEC = importlib.util.spec_from_file_location("memgallery_control_runner", MODULE_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def scenario(question_count: int = 1) -> dict:
    records = [
        {
            "memory_id": "s:session-0:round-0",
            "chronological_index": 0,
            "text": "user: red bicycle",
            "multimodal_text": "user: red bicycle",
            "image_ids": [],
            "source_image_id": None,
        },
        {
            "memory_id": "s:session-0:round-1",
            "chronological_index": 1,
            "text": "assistant: blue ocean",
            "multimodal_text": "assistant: blue ocean",
            "image_ids": ["data/image/ocean.jpg"],
            "source_image_id": "IMG_2",
        },
    ]
    queries = [
        {
            "qid": f"s:{index}",
            "question": "What was red?",
            "retrieval_query_text": "red",
            "speaker_a": "user",
            "speaker_b": "assistant",
            "category": "",
            "question_image_id": None,
        }
        for index in range(question_count)
    ]
    return {"scenario": "s", "memory_records": records, "queries": queries}


class TickClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 0.01
        return self.value


def accepted_answer(request):
    return "A bicycle.", {
        "schema_version": "agentenhance.memgallery_endpoint_call.v1",
        "call_category": "final_answer",
        "status": "ACCEPTED",
        "attempts": 1,
        "retry_count": 0,
        "prompt_tokens": 20,
        "completion_tokens": 3,
        "total_tokens": 23,
        "wall_seconds": 0.1,
    }


class MemGalleryControlRunnerTests(unittest.TestCase):
    def test_bm25_composes_retrieval_budget_request_and_prediction(self) -> None:
        result = runner.run_control_scenario(
            "bm25",
            scenario(),
            seed=0,
            token_count=lambda text: len(text.split()),
            answer_call=accepted_answer,
            clock=TickClock(),
        )
        self.assertEqual(result["accepted_questions"], 1)
        prediction = result["predictions"][0]
        self.assertEqual(prediction["status"], "ACCEPTED")
        self.assertEqual(prediction["retrieved_memory_ids"][0], "s:session-0:round-0")
        self.assertEqual(result["call_records"][0]["qid"], "s:0")
        self.assertEqual(result["scores_observed"], 0)

    def test_answer_failure_becomes_denominator_preserving_row_and_continues(self) -> None:
        calls = []

        def answer_call(request):
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError("unit timeout")
            return accepted_answer(request)

        result = runner.run_control_scenario(
            "no-memory",
            scenario(question_count=2),
            seed=1,
            token_count=lambda text: len(text.split()),
            answer_call=answer_call,
            clock=TickClock(),
        )
        self.assertEqual([row["status"] for row in result["predictions"]], ["FAILED", "ACCEPTED"])
        self.assertEqual(result["questions"], 2)
        self.assertEqual(result["failed_questions"], 1)
        self.assertEqual(result["predictions"][0]["error_type"], "TimeoutError")
        self.assertEqual(result["call_records"][0]["retry_count"], 0)

    def test_full_multimodal_uses_raw_text_and_image_budget(self) -> None:
        captured = []

        def answer_call(request):
            captured.append(request)
            return accepted_answer(request)

        result = runner.run_control_scenario(
            "full-memory-mm",
            scenario(),
            seed=2,
            token_count=lambda text: len(text.split()),
            answer_call=answer_call,
            clock=TickClock(),
        )
        self.assertEqual(result["predictions"][0]["retrieval_count"], 2)
        content = captured[0]["messages"][1]["content"]
        self.assertTrue(any(item.get("type") == "image_ref" for item in content))
        self.assertEqual(result["retrieval_traces"][0]["budget"]["images"], 1)

    def test_dense_method_requires_both_frozen_vector_surfaces(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires frozen"):
            runner.run_control_scenario(
                "naive-rag",
                scenario(),
                seed=0,
                token_count=lambda text: 1,
                answer_call=accepted_answer,
                clock=TickClock(),
            )

    def test_dense_vectors_flow_through_same_prediction_contract(self) -> None:
        result = runner.run_control_scenario(
            "naive-rag",
            scenario(),
            seed=0,
            token_count=lambda text: 1,
            answer_call=accepted_answer,
            dense_document_vectors=[[1.0, 0.0], [0.0, 1.0]],
            dense_query_vector=lambda query: [1.0, 0.0],
            clock=TickClock(),
        )
        self.assertEqual(result["predictions"][0]["retrieved_memory_ids"][0], "s:session-0:round-0")
        self.assertEqual(result["predictions"][0]["schema_version"], "agentenhance.memgallery_prediction.v1")

    def test_retrieval_failure_does_not_fabricate_an_answer_call(self) -> None:
        def broken_vector(query):
            raise RuntimeError("embedding failed")

        result = runner.run_control_scenario(
            "naive-rag",
            scenario(),
            seed=0,
            token_count=lambda text: 1,
            answer_call=accepted_answer,
            dense_document_vectors=[[1.0, 0.0], [0.0, 1.0]],
            dense_query_vector=broken_vector,
            clock=TickClock(),
        )
        self.assertEqual(result["predictions"][0]["status"], "FAILED")
        self.assertEqual(result["retrieval_traces"][0]["failure_stage"], "retrieval")
        self.assertEqual(result["call_records"], [])


if __name__ == "__main__":
    unittest.main()
