from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "memgallery_endpoint_client.py"
SPEC = importlib.util.spec_from_file_location("memgallery_endpoint_client", MODULE_PATH)
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


def abstract_request(image: str | None = None) -> dict:
    content = [{"type": "text", "text": "question"}]
    if image:
        content.append({"type": "image_ref", "image_id": image})
    return {
        "model": "Qwen3-VL-8B-Instruct",
        "temperature": 0.0,
        "max_tokens": 128,
        "seed": 0,
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": content},
        ],
    }


def valid_response(content: str = "Red.") -> bytes:
    return json.dumps(
        {
            "id": "chatcmpl-unit",
            "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }
    ).encode("utf-8")


class MemGalleryEndpointClientTests(unittest.TestCase):
    def test_image_expansion_binds_bytes_hash_mime_and_position(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            image = root / "data" / "image" / "scene" / "a.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"frozen-image")
            digest = hashlib.sha256(b"frozen-image").hexdigest()
            transport, evidence = client.prepare_transport_request(
                abstract_request("data/image/scene/a.png"),
                dataset_root=root,
                allowed_image_sha256={"data/image/scene/a.png": digest},
            )
            expanded = transport["messages"][1]["content"][1]
            self.assertEqual(expanded["type"], "image_url")
            self.assertTrue(expanded["image_url"]["url"].startswith("data:image/png;base64,"))
            self.assertEqual(evidence["image_count"], 1)
            self.assertEqual(evidence["image_bytes"], len(b"frozen-image"))
            self.assertEqual(evidence["images"][0]["sha256"], digest)
            self.assertEqual(evidence["images"][0]["content_position"], 1)

    def test_image_hash_drift_and_path_escape_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            image = root / "data" / "image" / "a.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"actual")
            with self.assertRaisesRegex(ValueError, "SHA-256 drift"):
                client.prepare_transport_request(
                    abstract_request("data/image/a.jpg"),
                    dataset_root=root,
                    allowed_image_sha256={"data/image/a.jpg": "0" * 64},
                )
            with self.assertRaisesRegex(ValueError, "unsafe"):
                client.prepare_transport_request(
                    abstract_request("data/image/../secret.jpg"),
                    dataset_root=root,
                    allowed_image_sha256={},
                )

    def test_image_symlink_is_rejected_even_when_bytes_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            image_dir = root / "data" / "image"
            image_dir.mkdir(parents=True)
            target = image_dir / "target.jpg"
            target.write_bytes(b"frozen")
            link = image_dir / "link.jpg"
            link.symlink_to(target)
            digest = hashlib.sha256(b"frozen").hexdigest()
            with self.assertRaisesRegex(ValueError, "symlink"):
                client.prepare_transport_request(
                    abstract_request("data/image/link.jpg"),
                    dataset_root=root,
                    allowed_image_sha256={"data/image/link.jpg": digest},
                )

    def test_success_records_exact_usage_and_single_attempt(self) -> None:
        calls = []

        def opener(request, timeout):
            calls.append((request, timeout))
            return FakeResponse(valid_response())

        ticks = iter([4.0, 4.25])
        prediction, record = client.execute_chat_completion(
            abstract_request(),
            endpoint="http://127.0.0.1:18320/v1/chat/completions",
            timeout_seconds=30.0,
            opener=opener,
            clock=lambda: next(ticks),
        )
        self.assertEqual(prediction, "Red.")
        self.assertEqual(len(calls), 1)
        self.assertEqual(record["attempts"], 1)
        self.assertEqual(record["retry_count"], 0)
        self.assertEqual(record["total_tokens"], 12)
        self.assertEqual(record["wall_seconds"], 0.25)

    def test_failure_is_terminal_and_retains_call_record(self) -> None:
        calls = []

        def opener(request, timeout):
            calls.append(1)
            raise TimeoutError("unit timeout")

        ticks = iter([1.0, 3.0])
        with self.assertRaises(client.EndpointCallError) as caught:
            client.execute_chat_completion(
                abstract_request(),
                endpoint="http://127.0.0.1:18320/v1/chat/completions",
                timeout_seconds=5.0,
                opener=opener,
                clock=lambda: next(ticks),
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(caught.exception.record["status"], "FAILED")
        self.assertEqual(caught.exception.record["retry_count"], 0)
        self.assertEqual(caught.exception.record["error_type"], "TimeoutError")

    def test_empty_prediction_and_usage_drift_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty prediction"):
            client.parse_chat_completion(json.loads(valid_response("  ")))
        payload = json.loads(valid_response())
        payload["usage"]["total_tokens"] = 99
        with self.assertRaisesRegex(ValueError, "sum exactly"):
            client.parse_chat_completion(payload)

    def test_malformed_json_response_is_one_terminal_failure(self) -> None:
        calls = []

        def opener(request, timeout):
            calls.append(1)
            return FakeResponse(b"not-json")

        ticks = iter([2.0, 2.1])
        with self.assertRaises(client.EndpointCallError) as caught:
            client.execute_chat_completion(
                abstract_request(),
                endpoint="http://127.0.0.1:18320/v1/chat/completions",
                timeout_seconds=5.0,
                opener=opener,
                clock=lambda: next(ticks),
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(caught.exception.record["attempts"], 1)
        self.assertEqual(caught.exception.record["retry_count"], 0)
        self.assertEqual(caught.exception.record["error_type"], "ValueError")

    def test_only_loopback_http_chat_endpoint_is_allowed(self) -> None:
        invalid = [
            "https://127.0.0.1:18320/v1/chat/completions",
            "http://localhost:18320/v1/chat/completions",
            "http://10.0.0.1:18320/v1/chat/completions",
            "http://127.0.0.1:18320/v1/embeddings",
            "http://127.0.0.1:80/v1/chat/completions",
        ]
        for endpoint in invalid:
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(ValueError, "127.0.0.1"):
                    client.validate_local_endpoint(endpoint)


if __name__ == "__main__":
    unittest.main()
