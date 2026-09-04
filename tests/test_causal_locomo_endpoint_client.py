from __future__ import annotations

import json
import math
import unittest

from scripts import causal_locomo_endpoint_client as client
from scripts.causal_locomo_five_method_overlay import run_method


class FakeResponse:
    def __init__(self, payload: bytes, status: int = 200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


def chat_payload(text: str = "answer") -> bytes:
    return json.dumps(
        {
            "id": "chatcmpl-test",
            "model": "Qwen3-VL-8B-Instruct",
            "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }
    ).encode("utf-8")


def embedding_payload(vector: list[float] | None = None) -> bytes:
    vector = vector if vector is not None else [1.0] + [0.0] * 1023
    return json.dumps(
        {
            "id": "embd-test",
            "model": "text-embedding-3-small",
            "object": "list",
            "data": [{"object": "embedding", "index": 0, "embedding": vector}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 0, "total_tokens": 4},
        }
    ).encode("utf-8")


def answer_request() -> dict:
    return {
        "model": "Qwen3-VL-8B-Instruct",
        "temperature": 0.0,
        "max_tokens": 600,
        "seed": 0,
        "messages": [{"role": "user", "content": "question"}],
    }


def view() -> dict:
    return {
        "schema_version": "agentenhance.causal_locomo_inference_view.v1",
        "example_id": "e1",
        "task_family": "factual_memory_qa",
        "past_sessions": [{"session_id": "s1", "timestamp": 1, "content": "history"}],
        "current_task": {"task_id": "q1", "instruction": "question", "recipient_type": None, "domain": "qa"},
        "memory_bank": [{"memory_id": "m1", "content": "memory", "timestamp": 1, "source_session_id": "s1"}],
    }


class EndpointClientTests(unittest.TestCase):
    def test_only_exact_loopback_paths_are_accepted(self) -> None:
        client.validate_loopback_endpoint("http://127.0.0.1:18120/v1/chat/completions", "/v1/chat/completions")
        client.validate_loopback_endpoint("http://127.0.0.1:18113/v1/embeddings", "/v1/embeddings")
        for endpoint in (
            "https://127.0.0.1:18120/v1/chat/completions",
            "http://localhost:18120/v1/chat/completions",
            "http://10.0.0.1:18120/v1/chat/completions",
            "http://127.0.0.1:80/v1/chat/completions",
        ):
            with self.assertRaisesRegex(ValueError, "127.0.0.1"):
                client.validate_loopback_endpoint(endpoint, "/v1/chat/completions")

    def test_chat_success_is_one_attempt_with_exact_usage(self) -> None:
        calls = []
        ticks = iter([1.0, 1.25])

        def opener(request, timeout):
            calls.append((request, timeout))
            return FakeResponse(chat_payload())

        result = client.execute_answer(
            answer_request(), endpoint="http://127.0.0.1:18120/v1/chat/completions",
            timeout_seconds=30.0, opener=opener, clock=lambda: next(ticks)
        )
        self.assertEqual(result["text"], "answer")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["call"]["attempts"], 1)
        self.assertEqual(result["call"]["retry_count"], 0)
        self.assertEqual(result["call"]["total_tokens"], 12)
        self.assertEqual(result["call"]["wall_seconds"], 0.25)

    def test_chat_request_identity_is_fail_closed(self) -> None:
        request = answer_request()
        request["temperature"] = 0.1
        with self.assertRaisesRegex(ValueError, "configuration drift"):
            client.execute_answer(
                request, endpoint="http://127.0.0.1:18120/v1/chat/completions", timeout_seconds=5.0
            )

    def test_embedding_success_requires_exact_1024_dimensions(self) -> None:
        ticks = iter([2.0, 2.5])
        result = client.execute_embedding(
            ["memory"], 1, endpoint="http://127.0.0.1:18113/v1/embeddings", timeout_seconds=10.0,
            opener=lambda request, timeout: FakeResponse(embedding_payload()), clock=lambda: next(ticks)
        )
        self.assertEqual(len(result["vectors"][0]), 1024)
        self.assertEqual(result["call"]["dimensions"], 1024)
        self.assertEqual(result["call"]["seed"], 1)

    def test_embedding_shape_nonfinite_and_zero_norm_are_rejected(self) -> None:
        for vector, message in (
            ([1.0] * 4, "dimension drift"),
            ([math.nan] + [0.0] * 1023, "non-finite"),
            ([0.0] * 1024, "invalid norm"),
        ):
            ticks = iter([1.0, 1.1])
            with self.assertRaises(client.EndpointCallError) as caught:
                client.execute_embedding(
                    ["memory"], 0, endpoint="http://127.0.0.1:18113/v1/embeddings", timeout_seconds=5.0,
                    opener=lambda request, timeout, v=vector: FakeResponse(embedding_payload(v)),
                    clock=lambda: next(ticks),
                )
            self.assertIn(message, str(caught.exception))

    def test_transport_failure_is_one_terminal_attempt(self) -> None:
        calls = []
        ticks = iter([5.0, 7.0])

        def opener(request, timeout):
            calls.append(1)
            raise TimeoutError("unit timeout")

        with self.assertRaises(client.EndpointCallError) as caught:
            client.execute_answer(
                answer_request(), endpoint="http://127.0.0.1:18120/v1/chat/completions",
                timeout_seconds=5.0, opener=opener, clock=lambda: next(ticks)
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(caught.exception.record["status"], "FAILED")
        self.assertEqual(caught.exception.record["retry_count"], 0)
        self.assertEqual(caught.exception.record["error_type"], "TimeoutError")

    def test_overlay_retains_failed_endpoint_call_record(self) -> None:
        ticks = iter([1.0, 2.0])

        def answer(request):
            return client.execute_answer(
                request, endpoint="http://127.0.0.1:18120/v1/chat/completions", timeout_seconds=1.0,
                opener=lambda request, timeout: (_ for _ in ()).throw(TimeoutError("timeout")),
                clock=lambda: next(ticks),
            )

        row = run_method(view(), method_id="cmi-no-memory", seed=0, answer=answer)
        self.assertEqual(row["status"], "FAILED")
        self.assertEqual(len(row["calls"]), 1)
        self.assertEqual(row["calls"][0]["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()

