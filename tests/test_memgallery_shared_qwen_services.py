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
MODULE_PATH = SCRIPTS / "manage_memgallery_shared_qwen_services.py"
SPEC = importlib.util.spec_from_file_location("manage_memgallery_shared_qwen_services", MODULE_PATH)
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


def model_identity(role: str) -> dict:
    spec = service.MODEL_SPECS[role]
    return {
        "role": role,
        "model_id": spec["model_id"],
        "revision": spec["revision"],
        "model_path": spec["path"],
        "placement_manifest_sha256": spec["manifest_sha256"],
        "model_inventory_sha256": spec["inventory_sha256"],
        "model_files": spec["files"],
        "model_bytes": spec["bytes"],
        "model_snapshot_sha256": ("a" if role == "chat" else "b") * 64,
    }


def encoded(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()


def model_response(role: str) -> dict:
    return {
        "object": "list",
        "data": [{"id": service.SERVICE_SPECS[role]["served_model"], "object": "model"}],
    }


def chat_smoke() -> dict:
    return {
        "id": "chat-1",
        "choices": [{"message": {"content": "READY"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
    }


def embedding_smoke() -> dict:
    return {
        "id": "embed-1",
        "model": service.SERVICE_SPECS["embedding"]["served_model"],
        "data": [{"index": 0, "embedding": [1.0] + [0.0] * 1023}],
        "usage": {"prompt_tokens": 3, "total_tokens": 3},
    }


class FakeProcess:
    def __init__(self, pid: int, returncode=None):
        self.pid = pid
        self.returncode = returncode

    def poll(self):
        return self.returncode


def fake_http(url: str, *, request_payload=None):
    if url.endswith("/models"):
        role = "chat" if ":18320/" in url else "embedding"
        payload = model_response(role)
    elif ":18320/" in url:
        payload = chat_smoke()
    else:
        payload = embedding_smoke()
    return payload, encoded(payload)


def prepare_paths(temporary: str):
    project = Path(temporary).resolve() / "AgentEnhance"
    scope = project / "runs"
    scope.mkdir(parents=True)
    release_path = project / "release.json"
    release_path.write_text(json.dumps(release_receipt()), encoding="utf-8")
    return project, scope, release_path


def write_ready_root(root: Path) -> dict:
    root.mkdir(parents=True)
    commands = {
        role: {
            "argv": service.build_launch_argv(
                role, service.INFER_PYTHON, Path(service.MODEL_SPECS[role]["path"])
            ),
            "environment": {
                "CUDA_VISIBLE_DEVICES": ",".join(
                    str(index) for index in service.SERVICE_SPECS[role]["gpu_indices"]
                ),
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_OFFLINE": "1",
            },
        }
        for role in service.ROLE_ORDER
    }
    (root / "commands.json").write_text(json.dumps(commands), encoding="utf-8")
    responses = {}
    for role in service.ROLE_ORDER:
        models_raw = encoded(model_response(role))
        smoke_payload = chat_smoke() if role == "chat" else embedding_smoke()
        smoke_raw = encoded(smoke_payload)
        (root / f"{role}-models-response.json").write_bytes(models_raw)
        (root / f"{role}-smoke-response.json").write_bytes(smoke_raw)
        responses[role] = (models_raw, smoke_raw, smoke_payload)
    ready = {
        "schema_version": "agentenhance.memgallery_shared_qwen_service_ready.v1",
        "status": "READY_FOR_MEMGALLERY",
        "models": {role: model_identity(role) for role in service.ROLE_ORDER},
        "services": {
            role: {
                **service.SERVICE_SPECS[role],
                "gpu_indices": list(service.SERVICE_SPECS[role]["gpu_indices"]),
                "pid": 12001 if role == "chat" else 12002,
                "process_group_id": 12001 if role == "chat" else 12002,
                "cmdline_sha256": "c" * 64,
                "command_sha256": service.sha256_bytes(
                    service.canonical_json_bytes(commands[role])
                ),
                "models_response_sha256": service.sha256_bytes(responses[role][0]),
                "readiness_polls": 1,
                "smoke": {
                    "request_sha256": service.sha256_bytes(
                        service.canonical_json_bytes(service._smoke_request(role))
                    ),
                    "response_sha256": service.sha256_bytes(responses[role][1]),
                    "response_bytes": len(responses[role][1]),
                    "attempts": 1,
                    "retry_count": 0,
                    **(
                        service.parse_chat_smoke(responses[role][2])
                        if role == "chat"
                        else service.parse_embedding_smoke(responses[role][2])
                    ),
                },
            }
            for role in service.ROLE_ORDER
        },
        "automatic_retries": 0,
        "benchmark_examples_read": 0,
        "predictions_observed": 0,
        "scores_observed": 0,
    }
    for name in (
        "service-record.json",
        "chat-readiness-attempts.jsonl",
        "embedding-readiness-attempts.jsonl",
        "chat.log",
        "embedding.log",
    ):
        (root / name).write_text(name, encoding="utf-8")
    (root / "service-ready.json").write_text(json.dumps(ready), encoding="utf-8")
    (root / "READY_FOR_MEMGALLERY").touch()
    return ready


class MemGallerySharedQwenServicesTests(unittest.TestCase):
    def test_signed_shared_model_snapshot_is_fully_rehashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "model"
            root.mkdir()
            files = {"config.json": b"config", "weights.safetensors": b"weights"}
            for name, body in files.items():
                (root / name).write_bytes(body)
            inventory = "".join(
                f"{service.sha256_file(root / name)}  {name}\n" for name in sorted(files)
            )
            (root / "MODEL_FILES_SHA256SUMS").write_text(inventory, encoding="utf-8")
            inventory_sha = service.sha256_file(root / "MODEL_FILES_SHA256SUMS")
            manifest = {
                "schema_version": "model_placement_manifest.v1",
                "model_id": "unit/model",
                "revision": "1" * 40,
                "file_count": 2,
                "total_bytes": sum(map(len, files.values())),
                "model_files_inventory_sha256": inventory_sha,
                "read_only_after_publish": True,
            }
            (root / "placement-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            spec = {
                "model_id": manifest["model_id"],
                "revision": manifest["revision"],
                "path": str(root),
                "manifest_sha256": service.sha256_file(root / "placement-manifest.json"),
                "inventory_sha256": inventory_sha,
                "files": 2,
                "bytes": manifest["total_bytes"],
            }
            with mock.patch.dict(service.MODEL_SPECS, {"unit": spec}, clear=True):
                observed = service.validate_model_snapshot("unit", root)
                self.assertEqual(observed["model_files"], 2)
                (root / "config.json").write_bytes(b"tampered")
                with self.assertRaisesRegex(ValueError, "file hash drift"):
                    service.validate_model_snapshot("unit", root)
                (root / "config.json").write_bytes(files["config.json"])
                (root / "weights.safetensors").unlink()
                (root / "weights.safetensors").symlink_to(root / "config.json")
                with self.assertRaisesRegex(ValueError, "missing or linked"):
                    service.validate_model_snapshot("unit", root)

    def test_launch_profiles_freeze_gpu_topology_and_multimodal_capacity(self) -> None:
        chat = service.build_launch_argv("chat", service.INFER_PYTHON, Path("/models/chat"))
        embedding = service.build_launch_argv(
            "embedding", service.INFER_PYTHON, Path("/models/embedding")
        )
        self.assertEqual(chat[chat.index("--tensor-parallel-size") + 1], "2")
        self.assertEqual(chat[chat.index("--dtype") + 1], "bfloat16")
        self.assertEqual(chat[chat.index("--limit-mm-per-prompt") + 1], '{"image":21,"video":0}')
        self.assertEqual(embedding[embedding.index("--tensor-parallel-size") + 1], "1")
        self.assertEqual(embedding[embedding.index("--runner") + 1], "pooling")
        self.assertEqual(embedding[embedding.index("--convert") + 1], "embed")
        self.assertEqual(
            embedding[embedding.index("--pooler-config") + 1],
            '{"dimensions":1024,"normalize":true}',
        )

    def test_gpu_parser_requires_all_exact_project_devices(self) -> None:
        observed = service.parse_gpu_table("0, 9\n1, 10\n3, 11\n4, 12\n5, 13\n")
        self.assertEqual(observed, {1: 10, 3: 11, 4: 12})
        with self.assertRaisesRegex(ValueError, "required GPU"):
            service.parse_gpu_table("1, 10\n3, 11\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            service.parse_gpu_table("1, 10\n1, 11\n3, 0\n4, 0\n")

    def test_readiness_and_smoke_parsers_fail_closed(self) -> None:
        for role in service.ROLE_ORDER:
            service.parse_models_response(role, model_response(role))
        service.parse_chat_smoke(chat_smoke())
        self.assertEqual(service.parse_embedding_smoke(embedding_smoke())["dimensions"], 1024)
        invalid = model_response("chat")
        invalid["data"][0]["id"] = "wrong"
        with self.assertRaisesRegex(ValueError, "identity"):
            service.parse_models_response("chat", invalid)
        invalid_vector = embedding_smoke()
        invalid_vector["data"][0]["embedding"] = [0.0] * 1024
        with self.assertRaisesRegex(ValueError, "zero"):
            service.parse_embedding_smoke(invalid_vector)

    def test_active_release_is_rejected_before_root_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, scope, release_path = prepare_paths(temporary)
            payload = release_receipt()
            payload["status"] = "RUNNING"
            release_path.write_text(json.dumps(payload), encoding="utf-8")
            root = scope / "service"
            with self.assertRaisesRegex(ValueError, "status"):
                service.start_services(
                    output_root=root,
                    allowed_run_scopes=[scope],
                    release_receipt_path=release_path,
                    chat_model_path=Path(service.MODEL_SPECS["chat"]["path"]),
                    embedding_model_path=Path(service.MODEL_SPECS["embedding"]["path"]),
                )
            self.assertFalse(root.exists())

    def test_root_collision_is_rejected_before_model_rehash_or_gpu_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, scope, release_path = prepare_paths(temporary)
            root = scope / "service"
            root.mkdir()
            with (
                mock.patch.object(service, "validate_model_snapshot") as model_check,
                mock.patch.object(service, "observe_gpu_headroom") as gpu_check,
            ):
                with self.assertRaisesRegex(ValueError, "existing"):
                    service.start_services(
                        output_root=root,
                        allowed_run_scopes=[scope],
                        release_receipt_path=release_path,
                        chat_model_path=project / "chat",
                        embedding_model_path=project / "embedding",
                    )
            model_check.assert_not_called()
            gpu_check.assert_not_called()

    def test_ready_receipt_rehash_rejects_response_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "AgentEnhance" / "runs" / "service"
            ready = write_ready_root(root)
            service.validate_ready_receipt(root, ready)
            (root / "embedding-smoke-response.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "smoke evidence drift"):
                service.validate_ready_receipt(root, ready)

    def test_start_creates_two_owned_ready_services_and_no_terminal_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, scope, release_path = prepare_paths(temporary)
            root = scope / "service"
            processes = [FakeProcess(12001), FakeProcess(12002)]
            with (
                mock.patch.object(service, "validate_model_snapshot", side_effect=lambda role, path: model_identity(role)),
                mock.patch.object(service, "validate_python", return_value=service.INFER_PYTHON),
                mock.patch.object(service, "observe_gpu_headroom", return_value={1: 0, 3: 0, 4: 0}),
                mock.patch.object(service, "require_ports_free"),
                mock.patch.object(service.subprocess, "Popen", side_effect=processes) as popen,
                mock.patch.object(service.os, "getpgid", side_effect=lambda pid: pid),
                mock.patch.object(service, "proc_cmdline", side_effect=lambda pid: f"python-{pid}".encode()),
                mock.patch.object(service, "_http_json", side_effect=fake_http) as http,
            ):
                ready = service.start_services(
                    output_root=root,
                    allowed_run_scopes=[scope],
                    release_receipt_path=release_path,
                    chat_model_path=project / "chat",
                    embedding_model_path=project / "embedding",
                )
            self.assertEqual(ready["status"], "READY_FOR_MEMGALLERY")
            self.assertEqual(set(ready["services"]), {"chat", "embedding"})
            self.assertEqual(ready["services"]["chat"]["gpu_indices"], [3, 4])
            self.assertEqual(ready["services"]["embedding"]["gpu_indices"], [1])
            self.assertEqual(popen.call_count, 2)
            self.assertEqual(http.call_count, 4)
            self.assertTrue((root / "READY_FOR_MEMGALLERY").is_file())
            self.assertFalse((root / "EVIDENCE_SHA256SUMS").exists())

    def test_startup_process_exit_rejects_and_signs_partial_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, scope, release_path = prepare_paths(temporary)
            root = scope / "service"
            processes = [FakeProcess(12001, returncode=7), FakeProcess(12002)]
            with (
                mock.patch.object(service, "validate_model_snapshot", side_effect=lambda role, path: model_identity(role)),
                mock.patch.object(service, "validate_python", return_value=service.INFER_PYTHON),
                mock.patch.object(service, "observe_gpu_headroom", return_value={1: 0, 3: 0, 4: 0}),
                mock.patch.object(service, "require_ports_free"),
                mock.patch.object(service.subprocess, "Popen", side_effect=processes),
                mock.patch.object(service.os, "getpgid", side_effect=lambda pid: pid),
                mock.patch.object(service, "proc_cmdline", side_effect=lambda pid: f"python-{pid}".encode()),
                mock.patch.object(service, "_process_exists", return_value=False),
            ):
                with self.assertRaisesRegex(RuntimeError, "exited before readiness"):
                    service.start_services(
                        output_root=root,
                        allowed_run_scopes=[scope],
                        release_receipt_path=release_path,
                        chat_model_path=project / "chat",
                        embedding_model_path=project / "embedding",
                    )
            self.assertTrue((root / "TERMINAL_REJECTED").is_file())
            failure = json.loads((root / "service-failure.json").read_text())
            self.assertFalse(failure["same_root_retry_allowed"])
            self.assertEqual(set(failure["owned_process_cleanup"]), {"chat", "embedding"})
            self.assertGreaterEqual(len((root / "EVIDENCE_SHA256SUMS").read_text().splitlines()), 7)

    def test_stop_validates_each_owned_process_and_signs_twelve_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "AgentEnhance" / "runs" / "service"
            write_ready_root(root)
            live = {12001: True, 12002: True}

            def terminate(pid):
                live[pid] = False
                return {"already_absent": False, "sigterm_sent": True, "sigkill_sent": False}

            with (
                mock.patch.object(service, "_process_exists", side_effect=lambda pid: live[pid]),
                mock.patch.object(
                    service, "validate_owned_process",
                    side_effect=lambda process: (process["pid"], process["process_group_id"]),
                ),
                mock.patch.object(service.os, "getpgid", side_effect=lambda pid: pid),
                mock.patch.object(service, "_terminate_pid", side_effect=terminate),
                mock.patch.object(service, "require_ports_free"),
            ):
                stop = service.stop_services(root)
            self.assertEqual(stop["status"], "TERMINAL_ACCEPTED_STOPPED")
            self.assertTrue(stop["processes_absent"])
            self.assertTrue((root / "TERMINAL_ACCEPTED_STOPPED").is_file())
            self.assertEqual(len((root / "EVIDENCE_SHA256SUMS").read_text().splitlines()), 12)

    def test_stop_ownership_failure_still_attempts_other_role_and_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "AgentEnhance" / "runs" / "service"
            write_ready_root(root)
            live = {12001: True, 12002: True}

            def validate(process):
                if process["pid"] == 12002:
                    raise ValueError("command-line identity drift")
                return process["pid"], process["process_group_id"]

            def terminate(pid):
                live[pid] = False
                return {"already_absent": False, "sigterm_sent": True, "sigkill_sent": False}

            with (
                mock.patch.object(service, "_process_exists", side_effect=lambda pid: live[pid]),
                mock.patch.object(service, "validate_owned_process", side_effect=validate),
                mock.patch.object(service.os, "getpgid", side_effect=lambda pid: pid),
                mock.patch.object(service, "_terminate_pid", side_effect=terminate),
                mock.patch.object(service, "require_ports_free"),
            ):
                with self.assertRaisesRegex(RuntimeError, "embedding"):
                    service.stop_services(root)
            self.assertFalse(live[12001])
            self.assertTrue(live[12002])
            self.assertTrue((root / "TERMINAL_REJECTED").is_file())
            failure = json.loads((root / "service-stop-failure.json").read_text())
            self.assertIn("embedding", failure["errors"])


if __name__ == "__main__":
    unittest.main()
