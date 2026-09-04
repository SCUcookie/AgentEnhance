from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "memgallery_embedding_artifact.py"
SPEC = importlib.util.spec_from_file_location("memgallery_embedding_artifact", MODULE_PATH)
assert SPEC and SPEC.loader
artifact = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artifact)


DATASET_IDENTITY = "1" * 64


def projection() -> list[dict]:
    return [
        {
            "scenario": "ava",
            "memory_records": [
                {"memory_id": "ava:m0", "chronological_index": 0, "text": "memory zero"},
                {"memory_id": "ava:m1", "chronological_index": 1, "text": "memory one"},
            ],
            "queries": [
                {
                    "qid": "ava:0",
                    "scenario": "ava",
                    "retrieval_query_text": "question zero",
                    "answer_sha256": "2" * 64,
                },
                {
                    "qid": "ava:1",
                    "scenario": "ava",
                    "retrieval_query_text": "question one",
                    "answer_sha256": "3" * 64,
                },
            ],
        }
    ]


def call(
    writer,
    role: str,
    texts: list[str],
    *,
    status: str = "ACCEPTED",
    batch_index: int = 0,
    input_offset: int = 0,
) -> dict:
    request = {
        "model": writer.profile["model"],
        "input": texts,
        "encoding_format": "float",
    }
    request_bytes = artifact.canonical_json_bytes(request)
    accepted = status == "ACCEPTED"
    return {
        "schema_version": "agentenhance.memgallery_embedding_call.v1",
        "call_category": "text_embedding",
        "input_role": role,
        "method_id": writer.method_id,
        "seed": writer.seed,
        "profile": writer.profile["profile"],
        "model": writer.profile["model"],
        "endpoint": "http://127.0.0.1:18322/v1/embeddings",
        "input_items": len(texts),
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "request_bytes": len(request_bytes),
        "attempts": 1,
        "retry_count": 0,
        "status": status,
        "http_status": 200 if accepted else None,
        "response_sha256": "4" * 64 if accepted else None,
        "response_bytes": 200 if accepted else 0,
        "wall_seconds": 0.1,
        "response_id": "emb-unit" if accepted else None,
        "dimensions": writer.profile["dimensions"],
        "prompt_tokens": len(texts),
        "completion_tokens": 0,
        "total_tokens": len(texts),
        "error_type": None if accepted else "TimeoutError",
        "error": None if accepted else "timeout",
        "batch_index": batch_index,
        "input_offset": input_offset,
    }


def vectors(count: int, dimensions: int) -> list[list[float]]:
    return [[float(index + 1)] + [0.0] * (dimensions - 1) for index in range(count)]


class MemGalleryEmbeddingArtifactTests(unittest.TestCase):
    def make_writer(self, scope: Path, name: str = "artifact"):
        return artifact.EmbeddingArtifactWriter(
            scope / name,
            allowed_run_scopes=[scope],
            method_id="hybrid-rag",
            seed=0,
            projections=projection(),
            dataset_semantic_identity_sha256=DATASET_IDENTITY,
            batch_size=2,
        )

    def complete(self, writer) -> dict:
        document_vectors = vectors(2, 1024)
        query_vectors = vectors(2, 1024)
        writer.append_accepted_batch(
            "document", document_vectors, call(writer, "document", ["memory zero", "memory one"])
        )
        writer.append_accepted_batch(
            "query", query_vectors, call(writer, "query", ["question zero", "question one"])
        )
        return writer.finalize()

    def test_complete_artifact_reloads_exact_runner_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            writer = self.make_writer(scope)
            identity = self.complete(writer)
            self.assertEqual(identity["status"], "TERMINAL_EMBEDDINGS_COMPLETE")
            loaded = artifact.load_embedding_artifact(
                writer.root,
                method_id="hybrid-rag",
                seed=0,
                projections=projection(),
                dataset_semantic_identity_sha256=DATASET_IDENTITY,
            )
            self.assertEqual(list(loaded["dense_document_vectors"]), ["ava"])
            self.assertEqual(len(loaded["dense_document_vectors"]["ava"]), 2)
            self.assertEqual(list(loaded["dense_query_vectors"]), ["ava:0", "ava:1"])
            self.assertEqual(len(loaded["dense_query_vectors"]["ava:0"]), 1024)
            self.assertEqual(len(loaded["call_records"]), 2)
            self.assertEqual(len((writer.root / "EVIDENCE_SHA256SUMS").read_text().splitlines()), 7)

    def test_request_hash_must_bind_next_frozen_text_slice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            writer = self.make_writer(Path(temporary).resolve())
            wrong = call(writer, "document", ["wrong", "memory one"])
            with self.assertRaisesRegex(ValueError, "next frozen text slice"):
                writer.append_accepted_batch("document", vectors(2, 1024), wrong)
            self.assertEqual((writer.root / "document-vectors.jsonl").read_bytes(), b"")

    def test_batch_order_offset_and_dimension_fail_closed_before_append(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            writer = self.make_writer(Path(temporary).resolve())
            bad_offset = call(writer, "document", ["memory zero"], input_offset=1)
            with self.assertRaisesRegex(ValueError, "input_offset"):
                writer.append_accepted_batch("document", vectors(1, 1024), bad_offset)
            good = call(writer, "document", ["memory zero"])
            with self.assertRaisesRegex(ValueError, "dimension"):
                writer.append_accepted_batch("document", vectors(1, 1023), good)
            self.assertEqual((writer.root / "document-vectors.jsonl").read_bytes(), b"")

    def test_failed_call_and_partial_vectors_are_retained_in_rejected_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            writer = self.make_writer(Path(temporary).resolve())
            writer.append_accepted_batch(
                "document", vectors(1, 1024), call(writer, "document", ["memory zero"])
            )
            failed = call(
                writer,
                "document",
                ["memory one"],
                status="FAILED",
                batch_index=1,
                input_offset=1,
            )
            writer.append_failed_call("document", failed)
            failure = writer.reject(TimeoutError("timeout"))
            self.assertEqual(failure["document_items_retained"], 1)
            self.assertEqual(failure["embedding_calls_retained"], 2)
            self.assertTrue((writer.root / "TERMINAL_REJECTED").is_file())
            self.assertEqual(len((writer.root / "embedding-calls.jsonl").read_text().splitlines()), 2)
            self.assertFalse((writer.root / "TERMINAL_EMBEDDINGS_COMPLETE").exists())

    def test_tamper_is_rejected_even_when_terminal_marker_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            writer = self.make_writer(Path(temporary).resolve())
            self.complete(writer)
            with (writer.root / "query-vectors.jsonl").open("ab") as handle:
                handle.write(b"{}\n")
            with self.assertRaisesRegex(ValueError, "hash drift"):
                artifact.load_embedding_artifact(
                    writer.root,
                    method_id="hybrid-rag",
                    seed=0,
                    projections=projection(),
                    dataset_semantic_identity_sha256=DATASET_IDENTITY,
                )

    def test_resigned_call_drift_is_semantically_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            writer = self.make_writer(Path(temporary).resolve())
            self.complete(writer)
            calls_path = writer.root / "embedding-calls.jsonl"
            rows = [json.loads(line) for line in calls_path.read_text().splitlines()]
            rows[0]["request_sha256"] = "f" * 64
            calls_path.write_bytes(b"".join(artifact.canonical_json_bytes(row) for row in rows))
            inventory_path = writer.root / "EVIDENCE_SHA256SUMS"
            inventory = []
            for line in inventory_path.read_text().splitlines():
                digest, name = line.split("  ", 1)
                if name == calls_path.name:
                    digest = artifact.sha256_file(calls_path)
                inventory.append(f"{digest}  {name}\n")
            inventory_path.write_text("".join(inventory))
            with self.assertRaisesRegex(ValueError, "request/text binding"):
                artifact.load_embedding_artifact(
                    writer.root,
                    method_id="hybrid-rag",
                    seed=0,
                    projections=projection(),
                    dataset_semantic_identity_sha256=DATASET_IDENTITY,
                )

    def test_projection_reorder_and_raw_answer_are_rejected(self) -> None:
        reordered = projection()
        reordered[0]["memory_records"].reverse()
        with self.assertRaisesRegex(ValueError, "identity"):
            artifact.build_embedding_surface(reordered)
        leaked = projection()
        leaked[0]["queries"][0]["answer"] = "gold"
        with self.assertRaisesRegex(ValueError, "raw answer"):
            artifact.build_embedding_surface(leaked)

    def test_existing_or_nested_output_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            (scope / "existing").mkdir()
            with self.assertRaisesRegex(ValueError, "existing"):
                self.make_writer(scope, "existing")
            nested_parent = scope / "nested"
            nested_parent.mkdir()
            with self.assertRaisesRegex(ValueError, "exact child"):
                artifact.EmbeddingArtifactWriter(
                    nested_parent / "artifact",
                    allowed_run_scopes=[scope],
                    method_id="hybrid-rag",
                    seed=0,
                    projections=projection(),
                    dataset_semantic_identity_sha256=DATASET_IDENTITY,
                    batch_size=2,
                )


if __name__ == "__main__":
    unittest.main()
