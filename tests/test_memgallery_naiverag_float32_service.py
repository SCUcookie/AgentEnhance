from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "manage_memgallery_naiverag_float32_service.py"
SPEC = importlib.util.spec_from_file_location("manage_memgallery_naiverag_float32_service", MODULE_PATH)
assert SPEC and SPEC.loader
service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)


def release_receipt() -> dict:
    gib = 1024**3
    return {
        "schema_version": "agentenhance.wma_wave1_release_gate_audit.v1",
        "status": "TERMINAL_ACCEPTED",
        "methods": 4,
        "seeds": 3,
        "method_seed_runs": 12,
        "accepted_units": 1800,
        "accepted_qa": 94872,
        "unit_hashes_verified": True,
        "blocked_processes": 0,
        "blocked_ports": [],
        "blocked_tmux_sessions": [],
        "future_root_collisions": [],
        "source_evidence_bytes": 20 * gib,
        "data1_free_bytes": 100 * gib,
        "data2_free_bytes": 100 * gib,
        "required_data2_free_bytes": 30 * gib,
        "scores_observed": 0,
        "official_values_used": False,
        "mutation_performed": False,
    }


def model_identity() -> dict:
    return {
        "model_path": "/data1/x/AgentEnhance/cache/models/gme",
        "model_materialization_root": "/data1/x/AgentEnhance/runs/gme-materialization",
        "model_materialization_sha256": "1" * 64,
        "model_inventory_sha256": "2" * 64,
        "model_snapshot_sha256": "3" * 64,
        "model_files": 24,
        "model_bytes": 8848245026,
    }


def ready_receipt() -> dict:
    return service.build_ready_receipt(
        pid=12345,
        pgid=12345,
        cmdline_sha256="4" * 64,
        command_sha256="5" * 64,
        models_response_sha256="6" * 64,
        model_identity=model_identity(),
        release_receipt_sha256="7" * 64,
        gpu_index=1,
        gpu_used_mib_before=0,
        readiness_polls=3,
        started_at="2026-09-04T00:00:00+00:00",
    )


class FakeProcess:
    def __init__(self, returncode=None):
        self.pid = 12345
        self.returncode = returncode

    def poll(self):
        return self.returncode


class FakeResponse:
    status = 200

    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size: int):
        return self.payload


class MemGalleryNaiveRagFloat32ServiceTests(unittest.TestCase):
    def test_release_receipt_accepts_complete_surface_and_rejects_drift(self) -> None:
        accepted = service.validate_release_receipt(release_receipt())
        self.assertEqual(accepted["accepted_units"], 1800)
        invalid = release_receipt()
        invalid["blocked_ports"] = [18113]
        with self.assertRaisesRegex(ValueError, "blocked_ports"):
            service.validate_release_receipt(invalid)
        invalid = release_receipt()
        invalid["data2_free_bytes"] = invalid["required_data2_free_bytes"] - 1
        with self.assertRaisesRegex(ValueError, "data2"):
            service.validate_release_receipt(invalid)

    def test_launch_argv_freezes_float32_loopback_single_gpu_profile(self) -> None:
        argv = service.build_launch_argv(
            service.INFER_PYTHON,
            Path("/project/scripts/run_vllm_gme_guarded.py"),
            Path(model_identity()["model_path"]),
        )
        self.assertEqual(argv[argv.index("--host") + 1], "127.0.0.1")
        self.assertEqual(argv[argv.index("--port") + 1], str(service.PORT))
        self.assertEqual(argv[argv.index("--dtype") + 1], "float32")
        self.assertEqual(argv[argv.index("--tensor-parallel-size") + 1], "1")
        self.assertEqual(argv[argv.index("--runner") + 1], "pooling")
        self.assertEqual(argv[argv.index("--convert") + 1], "embed")
        self.assertEqual(argv.count("--dtype"), 1)

    def test_gpu_observation_parser_is_exact_and_fail_closed(self) -> None:
        output = "0, 9\n1, 42\n3, 0\n"
        self.assertEqual(service.parse_gpu_used_mib(output, 1), 42)
        with self.assertRaisesRegex(ValueError, "exactly once"):
            service.parse_gpu_used_mib(output, 5)
        with self.assertRaisesRegex(ValueError, "malformed"):
            service.parse_gpu_used_mib("1,2,3", 1)

    def test_models_response_requires_one_exact_served_model(self) -> None:
        accepted = {"object": "list", "data": [{"id": service.SERVED_MODEL, "object": "model"}]}
        service.parse_models_response(accepted)
        with self.assertRaisesRegex(ValueError, "cardinality"):
            service.parse_models_response({"object": "list", "data": []})
        with self.assertRaisesRegex(ValueError, "identity"):
            service.parse_models_response({"object": "list", "data": [{"id": "wrong", "object": "model"}]})

    def test_ready_receipt_is_consumable_by_probe_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "service-ready.json"
            ready = ready_receipt()
            path.write_text(json.dumps(ready), encoding="utf-8")
            consumed = service.probe_capture.validate_service_ready(
                path, model_identity=model_identity(), endpoint=service.ENDPOINT
            )
            self.assertEqual(consumed["service_ready"]["dtype"], "float32")
            self.assertEqual(consumed["service_ready"]["automatic_retries"], 0)

    def test_start_writes_ready_root_after_one_exact_models_response(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary).resolve() / "AgentEnhance"
            scope = project / "runs"
            scope.mkdir(parents=True)
            release_path = project / "release.json"
            release_path.write_text(json.dumps(release_receipt()), encoding="utf-8")
            response = json.dumps(
                {"object": "list", "data": [{"id": service.SERVED_MODEL, "object": "model"}]}
            ).encode()
            root = scope / "service"
            with (
                mock.patch.object(service.probe_capture, "validate_model_snapshot", return_value=model_identity()),
                mock.patch.object(service, "validate_launcher", return_value=Path("/project/launcher.py")),
                mock.patch.object(service, "validate_python", return_value=service.INFER_PYTHON),
                mock.patch.object(service, "observe_gpu_used_mib", return_value=0),
                mock.patch.object(service, "require_port_free"),
                mock.patch.object(service.subprocess, "Popen", return_value=FakeProcess()),
                mock.patch.object(service.os, "getpgid", return_value=12345),
                mock.patch.object(service, "proc_cmdline", return_value=b"python\0launcher.py\0"),
                mock.patch.object(service.urllib.request, "urlopen", return_value=FakeResponse(response)),
            ):
                ready = service.start_service(
                    output_root=root,
                    allowed_run_scopes=[scope],
                    release_receipt_path=release_path,
                    model_path=project / "cache" / "models" / "gme",
                    materialization_root=scope / "materialization",
                    prefetch_manifest=project / "manifest.json",
                    launcher=project / "launcher.py",
                    gpu_index=1,
                )
            self.assertEqual(ready["status"], "READY_FOR_PARITY_PROBE")
            self.assertEqual(ready["readiness_polls"], 1)
            self.assertTrue((root / "READY_FOR_PARITY_PROBE").is_file())
            self.assertFalse((root / "EVIDENCE_SHA256SUMS").exists())

    def test_startup_exit_is_rejected_and_failure_surface_signed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary).resolve() / "AgentEnhance"
            scope = project / "runs"
            scope.mkdir(parents=True)
            release_path = project / "release.json"
            release_path.write_text(json.dumps(release_receipt()), encoding="utf-8")
            root = scope / "service"
            with (
                mock.patch.object(service.probe_capture, "validate_model_snapshot", return_value=model_identity()),
                mock.patch.object(service, "validate_launcher", return_value=Path("/project/launcher.py")),
                mock.patch.object(service, "validate_python", return_value=service.INFER_PYTHON),
                mock.patch.object(service, "observe_gpu_used_mib", return_value=0),
                mock.patch.object(service, "require_port_free"),
                mock.patch.object(service.subprocess, "Popen", return_value=FakeProcess(returncode=7)),
                mock.patch.object(service.os, "getpgid", return_value=12345),
                mock.patch.object(service, "proc_cmdline", return_value=b"python\0launcher.py\0"),
                mock.patch.object(service, "_process_exists", return_value=False),
            ):
                with self.assertRaisesRegex(RuntimeError, "exited before readiness"):
                    service.start_service(
                        output_root=root,
                        allowed_run_scopes=[scope],
                        release_receipt_path=release_path,
                        model_path=project / "cache" / "models" / "gme",
                        materialization_root=scope / "materialization",
                        prefetch_manifest=project / "manifest.json",
                        launcher=project / "launcher.py",
                        gpu_index=1,
                    )
            self.assertTrue((root / "TERMINAL_REJECTED").is_file())
            self.assertEqual(len((root / "EVIDENCE_SHA256SUMS").read_text().splitlines()), 5)
            failure = json.loads((root / "service-failure.json").read_text())
            self.assertEqual(failure["error_type"], "RuntimeError")
            self.assertFalse(failure["same_root_retry_allowed"])

    def test_owned_process_requires_exact_pid_group_and_cmdline_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary).resolve()
            pid_root = proc / "12345"
            pid_root.mkdir()
            raw = b"python\0server.py\0"
            (pid_root / "cmdline").write_bytes(raw)
            ready = ready_receipt()
            ready["cmdline_sha256"] = service.sha256_bytes(raw)
            self.assertEqual(service.validate_owned_process(ready, proc), (12345, 12345))
            ready["process_group_id"] = 999
            with self.assertRaisesRegex(ValueError, "PID/process-group"):
                service.validate_owned_process(ready, proc)
            ready = ready_receipt()
            with self.assertRaisesRegex(ValueError, "command-line"):
                service.validate_owned_process(ready, proc)

    def test_launcher_requires_exact_frozen_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "launcher.py"
            path.write_bytes(b"launcher")
            with mock.patch.object(service, "LAUNCHER_SHA256", service.sha256_file(path)):
                self.assertEqual(service.validate_launcher(path), path)
            path.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "hash drift"):
                service.validate_launcher(path)

    def test_stop_seals_only_validated_owned_service_and_signs_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary).resolve() / "AgentEnhance"
            root = project / "runs" / "service"
            root.mkdir(parents=True)
            ready = ready_receipt()
            (root / "service-ready.json").write_text(json.dumps(ready), encoding="utf-8")
            (root / "READY_FOR_PARITY_PROBE").touch()
            for name in (
                "service-record.json",
                "command.json",
                "readiness-attempts.jsonl",
                "models-response.json",
                "service.log",
            ):
                (root / name).write_text(name, encoding="utf-8")
            with (
                mock.patch.object(service, "validate_owned_process", return_value=(12345, 12345)),
                mock.patch.object(service.os, "getpgid", return_value=12345),
                mock.patch.object(
                    service,
                    "_terminate_owned_process",
                    return_value={"sigterm_sent": True, "sigkill_sent": False},
                ),
                mock.patch.object(service, "_process_exists", return_value=False),
                mock.patch.object(service, "require_port_free"),
            ):
                result = service.stop_service(root)
            self.assertEqual(result["status"], "TERMINAL_ACCEPTED_STOPPED")
            self.assertTrue(result["process_absent"])
            self.assertTrue((root / "TERMINAL_ACCEPTED_STOPPED").is_file())
            self.assertEqual(len((root / "EVIDENCE_SHA256SUMS").read_text().splitlines()), 7)
            with self.assertRaisesRegex(ValueError, "already terminal"):
                service.stop_service(root)


if __name__ == "__main__":
    unittest.main()
