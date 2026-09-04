from __future__ import annotations

import copy
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_memgallery_naiverag_encoder_parity.py"
SPEC = importlib.util.spec_from_file_location("audit_memgallery_naiverag_encoder_parity", MODULE_PATH)
assert SPEC and SPEC.loader
parity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parity)


QUERY_WEIGHTS = (
    (8, 7, 6, 5, 4, 3, 2, 1),
    (1, 8, 2, 7, 3, 6, 4, 5),
    (2, 1, 8, 3, 7, 4, 6, 5),
    (3, 2, 1, 8, 4, 7, 5, 6),
)


def vector(values: list[float]) -> list[float]:
    return values + [0.0] * (parity.DIMENSIONS - len(values))


def probe_vectors() -> list[list[float]]:
    documents = [vector([0.0] * index + [1.0]) for index in range(8)]
    queries = [vector([float(value) for value in weights]) for weights in QUERY_WEIGHTS]
    return documents + queries


def evidence(backend: str, vectors: list[list[float]] | None = None) -> dict:
    rows = []
    for identity, values in zip(parity.probe_identity(), vectors or probe_vectors()):
        rows.append({**identity, "vector": values})
    return {
        "schema_version": "agentenhance.memgallery_naiverag_encoder_probe.v1",
        "backend": backend,
        "method_id": parity.METHOD_ID,
        "source_revision": parity.SOURCE_REVISION,
        "encoder_source_sha256": parity.ENCODER_SOURCE_SHA256,
        "function_config_sha256": parity.FUNCTION_CONFIG_SHA256,
        "model_repository": parity.MODEL_REPOSITORY,
        "model_revision": parity.MODEL_REVISION,
        "model_config_sha256": parity.MODEL_CONFIG_SHA256,
        "pooling_config_sha256": parity.POOLING_CONFIG_SHA256,
        "dimensions": parity.DIMENSIONS,
        "pooling": "last_token",
        "normalization": "cosine_after_encoding",
        "precision": "float32",
        "probe_set_sha256": parity.PROBE_SET_SHA256,
        "batch_size": 1 if backend == "official_direct_lmencoder" else parity.ENDPOINT_BATCH_SIZE,
        "vectors": rows,
        "scores_observed": 0,
    }


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")


class MemGalleryNaiveRagEncoderParityTests(unittest.TestCase):
    def test_identical_vectors_accept_endpoint_equivalence(self) -> None:
        result = parity.audit_parity(
            evidence("official_direct_lmencoder"),
            evidence("vllm_openai_input"),
        )
        self.assertEqual(result["status"], "TERMINAL_ACCEPTED_ENDPOINT_EQUIVALENT")
        self.assertEqual(result["decision"], "ENDPOINT_EQUIVALENT")
        self.assertAlmostEqual(result["minimum_self_cosine"], 1.0)
        self.assertTrue(result["exact_retrieval_rankings"])
        self.assertFalse(result["claim_eligible"])

    def test_small_numeric_drift_can_require_direct_encoder(self) -> None:
        endpoint_vectors = probe_vectors()
        endpoint_vectors[8] = copy.deepcopy(endpoint_vectors[8])
        endpoint_vectors[8][0] += 0.01
        result = parity.audit_parity(
            evidence("official_direct_lmencoder"),
            evidence("vllm_openai_input", endpoint_vectors),
        )
        self.assertEqual(result["status"], "TERMINAL_ACCEPTED_DIRECT_ENCODER_REQUIRED")
        self.assertEqual(result["decision"], "DIRECT_ENCODER_REQUIRED")
        self.assertGreater(result["maximum_retrieval_score_delta"], parity.MAX_RETRIEVAL_SCORE_DELTA)

    def test_ranking_drift_requires_direct_encoder(self) -> None:
        endpoint_vectors = probe_vectors()
        endpoint_vectors[0], endpoint_vectors[1] = endpoint_vectors[1], endpoint_vectors[0]
        result = parity.audit_parity(
            evidence("official_direct_lmencoder"),
            evidence("vllm_openai_input", endpoint_vectors),
        )
        self.assertFalse(result["exact_retrieval_rankings"])
        self.assertEqual(result["decision"], "DIRECT_ENCODER_REQUIRED")

    def test_identity_order_dimension_and_nonfinite_fail_closed(self) -> None:
        invalid = evidence("vllm_openai_input")
        invalid["model_revision"] = "f" * 40
        with self.assertRaisesRegex(ValueError, "identity drift"):
            parity.audit_parity(evidence("official_direct_lmencoder"), invalid)

        invalid = evidence("vllm_openai_input")
        invalid["vectors"][0], invalid["vectors"][1] = invalid["vectors"][1], invalid["vectors"][0]
        with self.assertRaisesRegex(ValueError, "identity/order drift"):
            parity.audit_parity(evidence("official_direct_lmencoder"), invalid)

        invalid = evidence("vllm_openai_input")
        invalid["vectors"][0]["vector"] = invalid["vectors"][0]["vector"][:-1]
        with self.assertRaisesRegex(ValueError, "dimension drift"):
            parity.audit_parity(evidence("official_direct_lmencoder"), invalid)

        invalid = evidence("vllm_openai_input")
        invalid["vectors"][0]["vector"][0] = math.inf
        with self.assertRaisesRegex(ValueError, "non-finite"):
            parity.audit_parity(evidence("official_direct_lmencoder"), invalid)

    def test_fresh_root_writes_endpoint_decision_and_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            direct_path = scope / "direct.json"
            endpoint_path = scope / "endpoint.json"
            write_json(direct_path, evidence("official_direct_lmencoder"))
            write_json(endpoint_path, evidence("vllm_openai_input"))
            root = scope / "audit"
            result = parity.audit_to_fresh_root(
                direct_path,
                endpoint_path,
                root,
                allowed_run_scopes=[scope],
            )
            self.assertEqual(result["decision"], "ENDPOINT_EQUIVALENT")
            self.assertTrue((root / "TERMINAL_ACCEPTED_ENDPOINT_EQUIVALENT").is_file())
            inventory = (root / "EVIDENCE_SHA256SUMS").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(inventory), 1)
            self.assertTrue(inventory[0].endswith("  parity-audit.json"))

    def test_fresh_root_writes_direct_required_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            direct_path = scope / "direct.json"
            endpoint_path = scope / "endpoint.json"
            endpoint_vectors = probe_vectors()
            endpoint_vectors[8][0] += 0.01
            write_json(direct_path, evidence("official_direct_lmencoder"))
            write_json(endpoint_path, evidence("vllm_openai_input", endpoint_vectors))
            root = scope / "audit"
            parity.audit_to_fresh_root(
                direct_path,
                endpoint_path,
                root,
                allowed_run_scopes=[scope],
            )
            self.assertTrue((root / "TERMINAL_ACCEPTED_DIRECT_ENCODER_REQUIRED").is_file())
            self.assertFalse((root / "TERMINAL_ACCEPTED_ENDPOINT_EQUIVALENT").exists())

    def test_existing_nested_and_symlink_roots_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            direct_path = scope / "direct.json"
            endpoint_path = scope / "endpoint.json"
            write_json(direct_path, evidence("official_direct_lmencoder"))
            write_json(endpoint_path, evidence("vllm_openai_input"))
            existing = scope / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(ValueError, "existing"):
                parity.audit_to_fresh_root(
                    direct_path, endpoint_path, existing, allowed_run_scopes=[scope]
                )
            nested_parent = scope / "nested"
            nested_parent.mkdir()
            with self.assertRaisesRegex(ValueError, "exact child"):
                parity.audit_to_fresh_root(
                    direct_path,
                    endpoint_path,
                    nested_parent / "audit",
                    allowed_run_scopes=[scope],
                )
            symlink_root = scope / "symlink"
            symlink_root.symlink_to(nested_parent, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "not a symlink"):
                parity.audit_to_fresh_root(
                    direct_path, endpoint_path, symlink_root, allowed_run_scopes=[scope]
                )

    def test_malformed_input_is_rejected_before_root_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            direct_path = scope / "direct.json"
            endpoint_path = scope / "endpoint.json"
            direct_path.write_bytes(b"not-json")
            write_json(endpoint_path, evidence("vllm_openai_input"))
            root = scope / "audit"
            with self.assertRaisesRegex(ValueError, "valid UTF-8 JSON"):
                parity.audit_to_fresh_root(
                    direct_path, endpoint_path, root, allowed_run_scopes=[scope]
                )
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
