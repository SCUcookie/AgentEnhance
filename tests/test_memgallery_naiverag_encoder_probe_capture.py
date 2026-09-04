from __future__ import annotations

import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "capture_memgallery_naiverag_encoder_probes.py"
SPEC = importlib.util.spec_from_file_location("capture_memgallery_naiverag_encoder_probes", MODULE_PATH)
assert SPEC and SPEC.loader
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


def model_identity() -> dict:
    return {
        "model_path": "/data1/x/AgentEnhance/cache/models/wma-r1-wave2-gme-20260903-v1",
        "model_materialization_root": "/data1/x/AgentEnhance/runs/gme-materialization",
        "model_materialization_sha256": "1" * 64,
        "model_inventory_sha256": "2" * 64,
        "model_snapshot_sha256": "3" * 64,
        "model_files": capture.EXPECTED_MODEL_FILES,
        "model_bytes": capture.EXPECTED_MODEL_BYTES,
    }


def vectors() -> list[list[float]]:
    rows = []
    for index in range(len(capture.parity.PROBES)):
        row = [0.0] * capture.parity.DIMENSIONS
        row[index] = 1.0
        rows.append(row)
    return rows


def service_payload(identity: dict) -> dict:
    return {
        "schema_version": "agentenhance.memgallery_naiverag_float32_service_ready.v1",
        "status": "READY_FOR_PARITY_PROBE",
        "endpoint": capture.ENDPOINT,
        "served_model": "gme-Qwen2-VL-2B-Instruct",
        "model_repository": capture.parity.MODEL_REPOSITORY,
        "model_revision": capture.parity.MODEL_REVISION,
        "model_path": identity["model_path"],
        "model_snapshot_sha256": identity["model_snapshot_sha256"],
        "dtype": "float32",
        "runner": "pooling",
        "convert": "embed",
        "tensor_parallel_size": 1,
        "automatic_retries": 0,
        "pid": 12345,
        "models_response_sha256": "4" * 64,
    }


class MemGalleryNaiveRagEncoderProbeCaptureTests(unittest.TestCase):
    def test_model_snapshot_is_fully_rehashed_and_tamper_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary).resolve() / "AgentEnhance"
            model = project / "cache" / "models" / "gme"
            materialization = project / "runs" / "materialization"
            pooling = model / "1_Pooling" / "config.json"
            config = model / "config.json"
            pooling.parent.mkdir(parents=True)
            materialization.mkdir(parents=True)
            pooling.write_bytes(b"pool")
            config.write_bytes(b"config")
            rows = [
                {"path": "1_Pooling/config.json", "bytes": 4, "sha256": capture.sha256_file(pooling)},
                {"path": "config.json", "bytes": 6, "sha256": capture.sha256_file(config)},
            ]
            manifest_path = project / "manifest.json"
            manifest = {
                "models": [
                    {
                        "repository": capture.parity.MODEL_REPOSITORY,
                        "revision": capture.parity.MODEL_REVISION,
                        "expected_files": [{"path": row["path"]} for row in rows],
                        "expected_total_bytes": 10,
                    }
                ]
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            manifest_sha = capture.sha256_file(manifest_path)
            record = {
                "schema_version": "agentenhance.hf_model_materialization.v4",
                "status": "TERMINAL_ACCEPTED",
                "repository": capture.parity.MODEL_REPOSITORY,
                "revision": capture.parity.MODEL_REVISION,
                "target": str(model),
                "source_manifest_sha256": manifest_sha,
                "network_retry_count": 0,
                "logical_requests_per_file": 1,
                "file_count": 2,
                "total_bytes": 10,
                "files": rows,
            }
            record_path = materialization / "model-materialization.json"
            sums_path = materialization / "MODEL_SHA256SUMS"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            sums_path.write_text(
                "".join(f"{row['sha256']}  {model / row['path']}\n" for row in rows),
                encoding="utf-8",
            )
            (materialization / "EVIDENCE_SHA256SUMS").write_text(
                f"{capture.sha256_file(record_path)}  {record_path}\n"
                f"{capture.sha256_file(sums_path)}  {sums_path}\n",
                encoding="utf-8",
            )
            (materialization / "TERMINAL_ACCEPTED").touch()
            patches = (
                mock.patch.object(capture, "MODEL_MANIFEST_SHA256", manifest_sha),
                mock.patch.object(capture, "EXPECTED_MODEL_FILES", 2),
                mock.patch.object(capture, "EXPECTED_MODEL_BYTES", 10),
                mock.patch.object(capture.parity, "MODEL_CONFIG_SHA256", capture.sha256_file(config)),
                mock.patch.object(capture.parity, "POOLING_CONFIG_SHA256", capture.sha256_file(pooling)),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                identity = capture.validate_model_snapshot(model, materialization, manifest_path)
                self.assertEqual(identity["model_files"], 2)
                self.assertEqual(identity["model_bytes"], 10)
                config.write_bytes(b"tamper")
                with self.assertRaisesRegex(ValueError, "byte drift"):
                    capture.validate_model_snapshot(model, materialization, manifest_path)

    def test_built_evidence_is_accepted_by_frozen_parity_gate(self) -> None:
        direct = capture.build_probe_evidence(
            "official_direct_lmencoder", vectors(), runtime={"network_requests": 0}
        )
        endpoint = capture.build_probe_evidence(
            "vllm_openai_input", vectors(), runtime={"endpoint_requests": 1}
        )
        result = capture.parity.audit_parity(direct, endpoint)
        self.assertEqual(result["decision"], "ENDPOINT_EQUIVALENT")
        self.assertEqual(direct["batch_size"], 1)
        self.assertEqual(endpoint["batch_size"], 12)

    def test_invalid_vector_denominator_dimension_and_values_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "denominator"):
            capture.build_probe_evidence("official_direct_lmencoder", vectors()[:-1], runtime={})
        invalid = vectors()
        invalid[0] = invalid[0][:-1]
        with self.assertRaisesRegex(ValueError, "dimension"):
            capture.build_probe_evidence("official_direct_lmencoder", invalid, runtime={})
        invalid = vectors()
        invalid[0][0] = math.nan
        with self.assertRaisesRegex(ValueError, "non-finite"):
            capture.build_probe_evidence("official_direct_lmencoder", invalid, runtime={})
        invalid = vectors()
        invalid[0] = [0.0] * capture.parity.DIMENSIONS
        with self.assertRaisesRegex(ValueError, "norm"):
            capture.build_probe_evidence("official_direct_lmencoder", invalid, runtime={})

    def test_direct_capture_root_is_complete_signed_and_result_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            root = scope / "direct"
            result = capture.capture_to_fresh_root(
                "official_direct_lmencoder",
                root,
                allowed_run_scopes=[scope],
                model_identity=model_identity(),
                capture=lambda: (vectors(), {"network_requests": 0, "automatic_retries": 0}),
            )
            self.assertEqual(result["status"], "TERMINAL_ACCEPTED")
            self.assertEqual(result["scores_observed"], 0)
            self.assertTrue((root / "TERMINAL_ACCEPTED").is_file())
            self.assertEqual(len((root / "EVIDENCE_SHA256SUMS").read_text().splitlines()), 3)
            evidence = json.loads((root / "probe-evidence.json").read_text())
            self.assertEqual(evidence["backend"], "official_direct_lmencoder")
            self.assertEqual(len(evidence["vectors"]), 12)

    def test_endpoint_capture_requires_and_persists_validated_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            identity = model_identity()
            service_path = scope / "service-ready.json"
            service_path.write_text(json.dumps(service_payload(identity)), encoding="utf-8")
            service = capture.validate_service_ready(
                service_path, model_identity=identity, endpoint=capture.ENDPOINT
            )
            root = scope / "endpoint"
            capture.capture_to_fresh_root(
                "vllm_openai_input",
                root,
                allowed_run_scopes=[scope],
                model_identity=identity,
                service_identity=service,
                capture=lambda: (vectors(), {"endpoint_requests": 1, "automatic_retries": 0}),
            )
            record = json.loads((root / "capture-record.json").read_text())
            self.assertEqual(record["service_identity"]["service_ready_sha256"], capture.sha256_file(service_path))

    def test_service_identity_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            identity = model_identity()
            payload = service_payload(identity)
            payload["dtype"] = "float16"
            path = scope / "service-ready.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "dtype"):
                capture.validate_service_ready(path, model_identity=identity, endpoint=capture.ENDPOINT)

    def test_capture_failure_is_terminal_retained_and_not_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            root = scope / "failed"

            def fail():
                raise RuntimeError("synthetic capture failure")

            with self.assertRaisesRegex(RuntimeError, "synthetic capture failure"):
                capture.capture_to_fresh_root(
                    "official_direct_lmencoder",
                    root,
                    allowed_run_scopes=[scope],
                    model_identity=model_identity(),
                    capture=fail,
                )
            self.assertTrue((root / "TERMINAL_REJECTED").is_file())
            failure = json.loads((root / "capture-failure.json").read_text())
            self.assertFalse(failure["same_root_retry_allowed"])
            self.assertEqual(failure["scores_observed"], 0)
            self.assertEqual(len((root / "EVIDENCE_SHA256SUMS").read_text().splitlines()), 2)

    def test_endpoint_failure_retains_one_shot_call_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            root = scope / "failed-endpoint"
            call = {"status": "FAILED", "attempts": 1, "retry_count": 0, "request_sha256": "5" * 64}

            def fail():
                raise capture.embedding_client.EndpointCallError("timeout", call)

            with self.assertRaisesRegex(capture.embedding_client.EndpointCallError, "timeout"):
                capture.capture_to_fresh_root(
                    "vllm_openai_input",
                    root,
                    allowed_run_scopes=[scope],
                    model_identity=model_identity(),
                    service_identity={"service_ready_sha256": "4" * 64},
                    capture=fail,
                )
            failure = json.loads((root / "capture-failure.json").read_text())
            self.assertEqual(failure["endpoint_call"], call)
            self.assertTrue((root / "TERMINAL_REJECTED").is_file())

    def test_backend_service_cross_binding_is_rejected_before_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            service = {"service_ready_sha256": "4" * 64}
            with self.assertRaisesRegex(ValueError, "requires a validated service"):
                capture.capture_to_fresh_root(
                    "vllm_openai_input",
                    scope / "endpoint",
                    allowed_run_scopes=[scope],
                    model_identity=model_identity(),
                    capture=lambda: (vectors(), {}),
                )
            with self.assertRaisesRegex(ValueError, "cannot bind"):
                capture.capture_to_fresh_root(
                    "official_direct_lmencoder",
                    scope / "direct",
                    allowed_run_scopes=[scope],
                    model_identity=model_identity(),
                    service_identity=service,
                    capture=lambda: (vectors(), {}),
                )
            self.assertFalse((scope / "endpoint").exists())
            self.assertFalse((scope / "direct").exists())

    def test_existing_nested_and_missing_model_identity_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary).resolve()
            existing = scope / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(ValueError, "existing"):
                capture.capture_to_fresh_root(
                    "official_direct_lmencoder",
                    existing,
                    allowed_run_scopes=[scope],
                    model_identity=model_identity(),
                    capture=lambda: (vectors(), {}),
                )
            nested = scope / "nested"
            nested.mkdir()
            with self.assertRaisesRegex(ValueError, "exact child"):
                capture.capture_to_fresh_root(
                    "official_direct_lmencoder",
                    nested / "capture",
                    allowed_run_scopes=[scope],
                    model_identity=model_identity(),
                    capture=lambda: (vectors(), {}),
                )
            incomplete = model_identity()
            incomplete.pop("model_snapshot_sha256")
            with self.assertRaisesRegex(ValueError, "model_snapshot_sha256"):
                capture.capture_to_fresh_root(
                    "official_direct_lmencoder",
                    scope / "missing",
                    allowed_run_scopes=[scope],
                    model_identity=incomplete,
                    capture=lambda: (vectors(), {}),
                )


if __name__ == "__main__":
    unittest.main()
