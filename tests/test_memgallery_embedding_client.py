from __future__ import annotations

import importlib.util
import json
import math
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "memgallery_embedding_client.py"
SPEC = importlib.util.spec_from_file_location("memgallery_embedding_client", MODULE_PATH)
assert SPEC and SPEC.loader
client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)


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


def response(model: str, dimensions: int, items: int, *, completion_tokens: bool = True) -> bytes:
    usage = {"prompt_tokens": items * 3, "total_tokens": items * 3}
    if completion_tokens:
        usage["completion_tokens"] = 0
    return json.dumps(
        {
            "id": "embd-unit",
            "model": model,
            "data": [
                {"index": index, "embedding": [float(index + 1)] + [0.0] * (dimensions - 1)}
                for index in range(items)
            ],
            "usage": usage,
        }
    ).encode("utf-8")


class MemGalleryEmbeddingClientTests(unittest.TestCase):
    def test_naive_rag_is_bound_to_gme_1536(self) -> None:
        calls = []

        def opener(request, timeout):
            calls.append(json.loads(request.data))
            return FakeResponse(response("gme-Qwen2-VL-2B-Instruct", 1536, 2))

        ticks = iter([1.0, 1.4])
        vectors, record = client.execute_embedding_batch(
            ["first", "second"],
            method_id="naive-rag",
            seed=0,
            input_role="document",
            endpoint="http://127.0.0.1:18321/v1/embeddings",
            timeout_seconds=30.0,
            opener=opener,
            clock=lambda: next(ticks),
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model"], "gme-Qwen2-VL-2B-Instruct")
        self.assertEqual(len(vectors), 2)
        self.assertEqual(len(vectors[0]), 1536)
        self.assertEqual(record["dimensions"], 1536)
        self.assertEqual(record["input_items"], 2)
        self.assertAlmostEqual(record["wall_seconds"], 0.4)
        self.assertNotIn("first", json.dumps(record))

    def test_hybrid_rag_is_bound_to_qwen_1024(self) -> None:
        def opener(request, timeout):
            return FakeResponse(response("Qwen3-VL-Embedding-2B", 1024, 1, completion_tokens=False))

        ticks = iter([2.0, 2.25])
        vectors, record = client.execute_embedding_batch(
            ["query"],
            method_id="hybrid-rag",
            seed=2,
            input_role="query",
            endpoint="http://127.0.0.1:18322/v1/embeddings",
            timeout_seconds=10.0,
            opener=opener,
            clock=lambda: next(ticks),
        )
        self.assertEqual(len(vectors[0]), 1024)
        self.assertEqual(record["model"], "Qwen3-VL-Embedding-2B")
        self.assertEqual(record["completion_tokens"], 0)
        self.assertEqual(record["attempts"], 1)
        self.assertEqual(record["retry_count"], 0)

    def test_batch_helper_preserves_order_and_offsets(self) -> None:
        observed = []

        def opener(request, timeout):
            payload = json.loads(request.data)
            observed.append(payload["input"])
            return FakeResponse(response("Qwen3-VL-Embedding-2B", 1024, len(payload["input"])))

        ticks = iter([0.0, 0.1, 0.1, 0.2, 0.2, 0.3])
        result = client.execute_embedding_batches(
            ["a", "b", "c", "d", "e"],
            method_id="hybrid-rag",
            seed=1,
            input_role="document",
            endpoint="http://127.0.0.1:18322/v1/embeddings",
            timeout_seconds=10.0,
            batch_size=2,
            opener=opener,
            clock=lambda: next(ticks),
        )
        self.assertEqual(observed, [["a", "b"], ["c", "d"], ["e"]])
        self.assertEqual(len(result["vectors"]), 5)
        self.assertEqual([row["input_offset"] for row in result["call_records"]], [0, 2, 4])
        self.assertEqual([row["batch_index"] for row in result["call_records"]], [0, 1, 2])

    def test_batch_failure_retains_prior_success_and_failed_attempt(self) -> None:
        attempts = 0

        def opener(request, timeout):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise TimeoutError("unit timeout")
            return FakeResponse(response("gme-Qwen2-VL-2B-Instruct", 1536, 2))

        ticks = iter([0.0, 0.1, 0.1, 0.4])
        with self.assertRaises(client.EmbeddingBatchError) as caught:
            client.execute_embedding_batches(
                ["a", "b", "c", "d"],
                method_id="naive-rag",
                seed=0,
                input_role="document",
                endpoint="http://127.0.0.1:18321/v1/embeddings",
                timeout_seconds=5.0,
                batch_size=2,
                opener=opener,
                clock=lambda: next(ticks),
            )
        self.assertEqual(attempts, 2)
        self.assertEqual(len(caught.exception.partial_vectors), 2)
        self.assertEqual([row["status"] for row in caught.exception.call_records], ["ACCEPTED", "FAILED"])
        self.assertEqual(caught.exception.call_records[-1]["error_type"], "TimeoutError")

    def test_response_index_reorder_is_terminal(self) -> None:
        payload = json.loads(response("Qwen3-VL-Embedding-2B", 1024, 2))
        payload["data"][0]["index"] = 1
        payload["data"][1]["index"] = 0

        def opener(request, timeout):
            return FakeResponse(json.dumps(payload).encode("utf-8"))

        ticks = iter([1.0, 1.1])
        with self.assertRaises(client.EndpointCallError) as caught:
            client.execute_embedding_batch(
                ["a", "b"],
                method_id="hybrid-rag",
                seed=0,
                input_role="query",
                endpoint="http://127.0.0.1:18322/v1/embeddings",
                timeout_seconds=5.0,
                opener=opener,
                clock=lambda: next(ticks),
            )
        self.assertIn("index/order", caught.exception.record["error"])

    def test_model_and_dimension_drift_are_rejected(self) -> None:
        wrong_model = json.loads(response("wrong", 1024, 1))
        with self.assertRaisesRegex(ValueError, "model identity"):
            client.parse_embedding_response(
                wrong_model,
                expected_model="Qwen3-VL-Embedding-2B",
                expected_dimensions=1024,
                expected_items=1,
            )
        wrong_dimension = json.loads(response("Qwen3-VL-Embedding-2B", 1023, 1))
        with self.assertRaisesRegex(ValueError, "dimension"):
            client.parse_embedding_response(
                wrong_dimension,
                expected_model="Qwen3-VL-Embedding-2B",
                expected_dimensions=1024,
                expected_items=1,
            )

    def test_nonfinite_zero_and_boolean_vectors_are_rejected(self) -> None:
        for value, pattern in ((0.0, "invalid norm"), (math.nan, "non-finite"), (True, "nonnumeric")):
            payload = json.loads(response("Qwen3-VL-Embedding-2B", 1024, 1))
            payload["data"][0]["embedding"] = [value] * 1024
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, pattern):
                    client.parse_embedding_response(
                        payload,
                        expected_model="Qwen3-VL-Embedding-2B",
                        expected_dimensions=1024,
                        expected_items=1,
                    )

    def test_usage_drift_is_rejected(self) -> None:
        payload = json.loads(response("Qwen3-VL-Embedding-2B", 1024, 1))
        payload["usage"]["completion_tokens"] = 1
        payload["usage"]["total_tokens"] = 4
        with self.assertRaisesRegex(ValueError, "must be zero"):
            client.parse_embedding_response(
                payload,
                expected_model="Qwen3-VL-Embedding-2B",
                expected_dimensions=1024,
                expected_items=1,
            )

    def test_method_input_seed_and_batch_boundaries_fail_closed(self) -> None:
        common = {
            "seed": 0,
            "input_role": "query",
            "endpoint": "http://127.0.0.1:18322/v1/embeddings",
            "timeout_seconds": 1.0,
        }
        with self.assertRaisesRegex(ValueError, "unsupported"):
            client.execute_embedding_batch(["x"], method_id="bm25", **common)
        with self.assertRaisesRegex(ValueError, "nonempty"):
            client.execute_embedding_batch(["  "], method_id="hybrid-rag", **common)
        with self.assertRaisesRegex(ValueError, "1..64"):
            client.execute_embedding_batch(["x"] * 65, method_id="hybrid-rag", **common)
        with self.assertRaisesRegex(ValueError, "seed"):
            client.execute_embedding_batch(
                ["x"], method_id="hybrid-rag", **{**common, "seed": 3}
            )

    def test_batch_helper_validates_full_surface_before_first_call(self) -> None:
        calls = []

        def opener(request, timeout):
            calls.append(1)
            return FakeResponse(response("Qwen3-VL-Embedding-2B", 1024, 64))

        with self.assertRaisesRegex(ValueError, "item 64"):
            client.execute_embedding_batches(
                ["valid"] * 64 + [""],
                method_id="hybrid-rag",
                seed=0,
                input_role="document",
                endpoint="http://127.0.0.1:18322/v1/embeddings",
                timeout_seconds=5.0,
                opener=opener,
            )
        self.assertEqual(calls, [])

    def test_only_loopback_embedding_endpoint_is_allowed(self) -> None:
        invalid = [
            "https://127.0.0.1:18321/v1/embeddings",
            "http://localhost:18321/v1/embeddings",
            "http://10.0.0.1:18321/v1/embeddings",
            "http://127.0.0.1:18321/v1/chat/completions",
            "http://127.0.0.1:80/v1/embeddings",
        ]
        for endpoint in invalid:
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(ValueError, "127.0.0.1"):
                    client.validate_local_endpoint(endpoint)


if __name__ == "__main__":
    unittest.main()
