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
MODULE_PATH = SCRIPTS / "run_memgallery_naiverag_parity_lifecycle.py"
SPEC = importlib.util.spec_from_file_location("run_memgallery_naiverag_parity_lifecycle", MODULE_PATH)
assert SPEC and SPEC.loader
lifecycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lifecycle)


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
        "model_materialization_root": "/data1/x/AgentEnhance/runs/materialization",
        "model_materialization_sha256": "1" * 64,
        "model_inventory_sha256": "2" * 64,
        "model_snapshot_sha256": "3" * 64,
        "model_files": 24,
        "model_bytes": 8848245026,
    }


def vectors() -> list[list[float]]:
    documents = []
    for index in range(8):
        vector = [0.0] * lifecycle.parity.DIMENSIONS
        vector[index] = 1.0
        documents.append(vector)
    weights = (
        (8, 7, 6, 5, 4, 3, 2, 1),
        (1, 8, 2, 7, 3, 6, 4, 5),
        (2, 1, 8, 3, 7, 4, 6, 5),
        (3, 2, 1, 8, 4, 7, 5, 6),
    )
    queries = []
    for row in weights:
        vector = [0.0] * lifecycle.parity.DIMENSIONS
        vector[:8] = row
        queries.append(vector)
    return documents + queries


def write_inventory(root: Path, names: tuple[str, ...]) -> None:
    (root / "EVIDENCE_SHA256SUMS").write_text(
        "".join(f"{lifecycle.sha256_file(root / name)}  {name}\n" for name in names),
        encoding="utf-8",
    )


class FakeRunner:
    def __init__(self, *, endpoint_drift: bool = False, fail_stage: str | None = None):
        self.endpoint_drift = endpoint_drift
        self.fail_stage = fail_stage
        self.calls: list[str] = []
        self.stop_calls = 0

    @staticmethod
    def value(argv, flag: str) -> str:
        return argv[argv.index(flag) + 1]

    def __call__(self, argv, environment):
        script = Path(argv[1]).name
        if script == "capture_memgallery_naiverag_encoder_probes.py":
            backend = self.value(argv, "--backend")
            stage = "direct_capture" if backend == "official_direct_lmencoder" else "endpoint_capture"
        elif script == "manage_memgallery_naiverag_float32_service.py":
            stage = "service_start" if argv[2] == "start" else "service_stop"
        else:
            stage = "parity_audit"
        self.calls.append(stage)
        if self.fail_stage == stage:
            if stage == "service_stop" and self.stop_calls > 0:
                pass
            else:
                if stage == "service_stop":
                    self.stop_calls += 1
                return lifecycle.subprocess.CompletedProcess(argv, 7, b"", b"synthetic failure")

        if stage in {"direct_capture", "endpoint_capture"}:
            root = Path(self.value(argv, "--output-root"))
            values = vectors()
            if stage == "endpoint_capture" and self.endpoint_drift:
                values[0], values[1] = values[1], values[0]
            lifecycle.probe_capture.capture_to_fresh_root(
                "official_direct_lmencoder" if stage == "direct_capture" else "vllm_openai_input",
                root,
                allowed_run_scopes=[root.parent],
                model_identity=model_identity(),
                service_identity=None if stage == "direct_capture" else {"service_ready_sha256": "4" * 64},
                capture=lambda: (values, {"automatic_retries": 0}),
            )
        elif stage == "service_start":
            root = Path(self.value(argv, "--output-root"))
            root.mkdir()
            for name in (
                "service-record.json",
                "command.json",
                "readiness-attempts.jsonl",
                "models-response.json",
                "service.log",
            ):
                (root / name).write_text(name, encoding="utf-8")
            (root / "service-ready.json").write_text("{}", encoding="utf-8")
            (root / "READY_FOR_PARITY_PROBE").touch()
        elif stage == "service_stop":
            self.stop_calls += 1
            root = Path(self.value(argv, "--service-root"))
            stop = {
                "status": "TERMINAL_ACCEPTED_STOPPED",
                "process_absent": True,
                "port_free": True,
                "scores_observed": 0,
            }
            (root / "service-stop.json").write_text(json.dumps(stop), encoding="utf-8")
            write_inventory(
                root,
                (
                    "service-record.json",
                    "command.json",
                    "readiness-attempts.jsonl",
                    "models-response.json",
                    "service-ready.json",
                    "service.log",
                    "service-stop.json",
                ),
            )
            (root / "TERMINAL_ACCEPTED_STOPPED").touch()
        else:
            direct = Path(self.value(argv, "--direct"))
            endpoint = Path(self.value(argv, "--endpoint"))
            root = Path(self.value(argv, "--output-root"))
            lifecycle.parity.audit_to_fresh_root(
                direct, endpoint, root, allowed_run_scopes=[root.parent]
            )
        return lifecycle.subprocess.CompletedProcess(argv, 0, b'{"status":"ok"}\n', b"")


class MemGalleryNaiveRagParityLifecycleTests(unittest.TestCase):
    def setup_paths(self, temporary: str):
        project = Path(temporary).resolve() / "AgentEnhance"
        run_scope = project / "runs"
        run_scope.mkdir(parents=True)
        release_path = project / "release.json"
        release_path.write_text(json.dumps(release_receipt()), encoding="utf-8")
        return project, run_scope, release_path

    def run_lifecycle_case(self, temporary: str, runner: FakeRunner):
        project, run_scope, release_path = self.setup_paths(temporary)
        with mock.patch.object(lifecycle.service, "validate_python", return_value=Path("/fake/python")):
            result = lifecycle.run_lifecycle(
                run_scope=run_scope,
                release_receipt=release_path,
                model_path=project / "cache" / "models" / "gme",
                materialization_root=run_scope / "materialization",
                prefetch_manifest=project / "manifest.json",
                launcher=SCRIPTS / "run_vllm_gme_guarded.py",
                gpu_index=1,
                script_root=SCRIPTS,
                runner=runner,
            )
        return result, lifecycle.lifecycle_roots(run_scope)

    def test_complete_lifecycle_accepts_endpoint_equivalence_after_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner()
            result, roots = self.run_lifecycle_case(temporary, runner)
            self.assertEqual(result["decision"], "ENDPOINT_EQUIVALENT")
            self.assertTrue(result["service_stopped"])
            self.assertEqual(runner.calls, [
                "direct_capture", "service_start", "endpoint_capture", "service_stop", "parity_audit"
            ])
            self.assertTrue((roots["controller"] / "TERMINAL_ACCEPTED_ENDPOINT_EQUIVALENT").is_file())
            self.assertEqual(len((roots["controller"] / "EVIDENCE_SHA256SUMS").read_text().splitlines()), 13)

    def test_complete_lifecycle_accepts_direct_required_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result, roots = self.run_lifecycle_case(temporary, FakeRunner(endpoint_drift=True))
            self.assertEqual(result["decision"], "DIRECT_ENCODER_REQUIRED")
            self.assertTrue((roots["controller"] / "TERMINAL_ACCEPTED_DIRECT_ENCODER_REQUIRED").is_file())
            self.assertTrue((roots["service"] / "TERMINAL_ACCEPTED_STOPPED").is_file())

    def test_endpoint_failure_still_stops_service_and_rejects_controller(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner(fail_stage="endpoint_capture")
            with self.assertRaisesRegex(lifecycle.StageFailure, "endpoint_capture"):
                self.run_lifecycle_case(temporary, runner)
            run_scope = Path(temporary).resolve() / "AgentEnhance" / "runs"
            roots = lifecycle.lifecycle_roots(run_scope)
            self.assertTrue((roots["service"] / "TERMINAL_ACCEPTED_STOPPED").is_file())
            self.assertTrue((roots["controller"] / "TERMINAL_REJECTED").is_file())
            failure = json.loads((roots["controller"] / "controller-failure.json").read_text())
            self.assertEqual(failure["service_cleanup"]["status"], "ACCEPTED")
            self.assertFalse(failure["same_root_retry_allowed"])

    def test_failed_regular_stop_gets_one_emergency_cleanup_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner(fail_stage="service_stop")
            with self.assertRaisesRegex(lifecycle.StageFailure, "service_stop"):
                self.run_lifecycle_case(temporary, runner)
            self.assertEqual(runner.stop_calls, 2)
            run_scope = Path(temporary).resolve() / "AgentEnhance" / "runs"
            roots = lifecycle.lifecycle_roots(run_scope)
            self.assertTrue((roots["service"] / "TERMINAL_ACCEPTED_STOPPED").is_file())
            failure = json.loads((roots["controller"] / "controller-failure.json").read_text())
            self.assertEqual(failure["service_cleanup"]["status"], "ACCEPTED")

    def test_root_collision_rejects_before_controller_or_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, run_scope, release_path = self.setup_paths(temporary)
            (run_scope / lifecycle.DIRECT_NAME).mkdir()
            runner = FakeRunner()
            with self.assertRaisesRegex(ValueError, "collision"):
                lifecycle.run_lifecycle(
                    run_scope=run_scope,
                    release_receipt=release_path,
                    model_path=project / "model",
                    materialization_root=run_scope / "materialization",
                    prefetch_manifest=project / "manifest.json",
                    launcher=SCRIPTS / "run_vllm_gme_guarded.py",
                    gpu_index=1,
                    script_root=SCRIPTS,
                    runner=runner,
                )
            self.assertEqual(runner.calls, [])
            self.assertFalse((run_scope / lifecycle.CONTROLLER_NAME).exists())

    def test_active_release_receipt_rejects_before_controller(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, run_scope, release_path = self.setup_paths(temporary)
            payload = release_receipt()
            payload["status"] = "RUNNING"
            release_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "status"):
                lifecycle.run_lifecycle(
                    run_scope=run_scope,
                    release_receipt=release_path,
                    model_path=project / "model",
                    materialization_root=run_scope / "materialization",
                    prefetch_manifest=project / "manifest.json",
                    launcher=SCRIPTS / "run_vllm_gme_guarded.py",
                    gpu_index=1,
                    script_root=SCRIPTS,
                    runner=FakeRunner(),
                )
            self.assertFalse((run_scope / lifecycle.CONTROLLER_NAME).exists())

    def test_tampered_child_inventory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "evidence.json").write_text("accepted", encoding="utf-8")
            write_inventory(root, ("evidence.json",))
            self.assertEqual(lifecycle.verify_inventory(root, expected_members=1), lifecycle.sha256_file(root / "EVIDENCE_SHA256SUMS"))
            (root / "evidence.json").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "hash drift"):
                lifecycle.verify_inventory(root, expected_members=1)


if __name__ == "__main__":
    unittest.main()
