#!/usr/bin/env python3
"""Start and stop the project-owned float32 GME parity service with signed evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

import capture_memgallery_naiverag_encoder_probes as probe_capture


INFER_PYTHON = Path("/data1/anaconda3/envs/clo-infer/bin/python3.11")
ENDPOINT = probe_capture.ENDPOINT
MODELS_ENDPOINT = "http://127.0.0.1:18322/v1/models"
PORT = 18322
SERVED_MODEL = "gme-Qwen2-VL-2B-Instruct"
LAUNCHER_SHA256 = "232da2e5837a4d1e1536566569002c540b52d95c57f5f39fc3a09f9060a0f787"
ALLOWED_GPU_INDICES = (1, 3, 4, 5)
MAX_PREFLIGHT_GPU_USED_MIB = 100
READINESS_ATTEMPTS = 180
READINESS_INTERVAL_SECONDS = 5
STOP_TIMEOUT_SECONDS = 120


def canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def now() -> str:
    return probe_capture.now()


def _atomic_create(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to replace existing service evidence: {path}")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_regular_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    return probe_capture._load_regular_json(path, label)


def validate_release_receipt(payload: object) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("Wave1 release receipt must be an object")
    expected = {
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
        "scores_observed": 0,
        "official_values_used": False,
        "mutation_performed": False,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise ValueError(f"Wave1 release receipt drift: {field}")
    for field in ("source_evidence_bytes", "data1_free_bytes", "data2_free_bytes", "required_data2_free_bytes"):
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"Wave1 release receipt invalid: {field}")
    if payload["data1_free_bytes"] < 40 * 1024**3:
        raise ValueError("Wave1 release receipt lacks data1 headroom")
    if payload["data2_free_bytes"] < payload["required_data2_free_bytes"]:
        raise ValueError("Wave1 release receipt lacks data2 archive headroom")
    return dict(payload)


def validate_launcher(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("GME launcher must be an absolute regular non-symlink file")
    resolved = path.resolve()
    if sha256_file(resolved) != LAUNCHER_SHA256:
        raise ValueError("GME launcher hash drift")
    return resolved


def validate_python(path: Path = INFER_PYTHON) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("inference Python is not the exact executable regular file")
    if path.resolve() != INFER_PYTHON:
        raise ValueError("inference Python path drift")
    return path.resolve()


def build_launch_argv(python: Path, launcher: Path, model_path: Path) -> list[str]:
    return [
        str(python),
        str(launcher),
        "--host",
        "127.0.0.1",
        "--port",
        str(PORT),
        "--model",
        str(model_path),
        "--served-model-name",
        SERVED_MODEL,
        "--runner",
        "pooling",
        "--convert",
        "embed",
        "--dtype",
        "float32",
        "--tensor-parallel-size",
        "1",
        "--max-model-len",
        "8192",
        "--gpu-memory-utilization",
        "0.90",
        "--max-num-seqs",
        "1",
        "--limit-mm-per-prompt",
        '{"image":1,"video":0}',
        "--trust-remote-code",
    ]


def parse_gpu_used_mib(output: str, gpu_index: int) -> int:
    matches: list[int] = []
    for line in output.splitlines():
        pieces = [piece.strip() for piece in line.split(",")]
        if len(pieces) != 2:
            raise ValueError("malformed nvidia-smi output")
        try:
            index, used = int(pieces[0]), int(pieces[1])
        except ValueError as exc:
            raise ValueError("nonnumeric nvidia-smi output") from exc
        if index == gpu_index:
            matches.append(used)
    if len(matches) != 1:
        raise ValueError("selected GPU was not observed exactly once")
    return matches[0]


def observe_gpu_used_mib(gpu_index: int) -> int:
    if gpu_index not in ALLOWED_GPU_INDICES:
        raise ValueError("GPU index is outside the frozen project allocation")
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,memory.used",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    used = parse_gpu_used_mib(completed.stdout, gpu_index)
    if used > MAX_PREFLIGHT_GPU_USED_MIB:
        raise RuntimeError(f"GPU {gpu_index} is not free enough: {used} MiB")
    return used


def require_port_free() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            candidate.bind(("127.0.0.1", PORT))
        except OSError as exc:
            raise RuntimeError(f"parity service port {PORT} is not free") from exc


def parse_models_response(payload: object) -> None:
    if not isinstance(payload, Mapping) or payload.get("object") != "list":
        raise ValueError("service models response is not an OpenAI list")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
        raise ValueError("service models response cardinality drift")
    if data[0].get("id") != SERVED_MODEL or data[0].get("object") != "model":
        raise ValueError("service models response identity drift")


def proc_cmdline(pid: int, proc_root: Path = Path("/proc")) -> bytes:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        raise ValueError("invalid service pid")
    path = proc_root / str(pid) / "cmdline"
    try:
        raw = path.read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError) as exc:
        raise RuntimeError("owned service process is not observable") from exc
    if not raw:
        raise RuntimeError("owned service process has an empty command line")
    return raw


def validate_owned_process(ready: Mapping[str, Any], proc_root: Path = Path("/proc")) -> tuple[int, int]:
    pid = ready.get("pid")
    pgid = ready.get("process_group_id")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1 or pgid != pid:
        raise ValueError("service PID/process-group identity drift")
    raw = proc_cmdline(pid, proc_root)
    if sha256_bytes(raw) != ready.get("cmdline_sha256"):
        raise ValueError("owned service command-line identity drift")
    return pid, pgid


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_owned_process(pid: int, *, timeout_seconds: int = STOP_TIMEOUT_SECONDS) -> dict[str, Any]:
    os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            return {"sigterm_sent": True, "sigkill_sent": False}
        time.sleep(1)
    os.killpg(pid, signal.SIGKILL)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            return {"sigterm_sent": True, "sigkill_sent": True}
        time.sleep(1)
    raise RuntimeError("owned service process group did not stop")


def build_ready_receipt(
    *,
    pid: int,
    pgid: int,
    cmdline_sha256: str,
    command_sha256: str,
    models_response_sha256: str,
    model_identity: Mapping[str, Any],
    release_receipt_sha256: str,
    gpu_index: int,
    gpu_used_mib_before: int,
    readiness_polls: int,
    started_at: str,
) -> dict[str, Any]:
    if pid <= 1 or pgid != pid or not all(
        len(value) == 64 and all(char in "0123456789abcdef" for char in value)
        for value in (cmdline_sha256, command_sha256, models_response_sha256, release_receipt_sha256)
    ):
        raise ValueError("invalid service-ready evidence inputs")
    if gpu_index not in ALLOWED_GPU_INDICES or not 0 <= gpu_used_mib_before <= MAX_PREFLIGHT_GPU_USED_MIB:
        raise ValueError("invalid service-ready GPU evidence")
    if not 1 <= readiness_polls <= READINESS_ATTEMPTS:
        raise ValueError("invalid service-ready readiness poll count")
    return {
        "schema_version": "agentenhance.memgallery_naiverag_float32_service_ready.v1",
        "status": "READY_FOR_PARITY_PROBE",
        "started_at": started_at,
        "ready_at": now(),
        "endpoint": ENDPOINT,
        "models_endpoint": MODELS_ENDPOINT,
        "served_model": SERVED_MODEL,
        "model_repository": probe_capture.parity.MODEL_REPOSITORY,
        "model_revision": probe_capture.parity.MODEL_REVISION,
        "model_path": model_identity["model_path"],
        "model_snapshot_sha256": model_identity["model_snapshot_sha256"],
        "model_materialization_sha256": model_identity["model_materialization_sha256"],
        "dtype": "float32",
        "runner": "pooling",
        "convert": "embed",
        "tensor_parallel_size": 1,
        "gpu_index": gpu_index,
        "gpu_used_mib_before": gpu_used_mib_before,
        "pid": pid,
        "process_group_id": pgid,
        "cmdline_sha256": cmdline_sha256,
        "command_sha256": command_sha256,
        "launcher_sha256": LAUNCHER_SHA256,
        "models_response_sha256": models_response_sha256,
        "release_receipt_sha256": release_receipt_sha256,
        "readiness_polls": readiness_polls,
        "automatic_retries": 0,
        "scores_observed": 0,
    }


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("ab") as handle:
        handle.write(canonical_json_bytes(dict(payload)))
        handle.flush()
        os.fsync(handle.fileno())


def start_service(
    *,
    output_root: Path,
    allowed_run_scopes: Sequence[Path],
    release_receipt_path: Path,
    model_path: Path,
    materialization_root: Path,
    prefetch_manifest: Path,
    launcher: Path,
    gpu_index: int,
) -> dict[str, Any]:
    release, release_bytes = _load_regular_json(release_receipt_path, "Wave1 release receipt")
    validate_release_receipt(release)
    model_identity = probe_capture.validate_model_snapshot(model_path, materialization_root, prefetch_manifest)
    launcher = validate_launcher(launcher)
    python = validate_python()
    gpu_used = observe_gpu_used_mib(gpu_index)
    require_port_free()
    if not output_root.is_absolute() or output_root.is_symlink():
        raise ValueError("service output root must be absolute and not a symlink")
    scopes = [scope.resolve() for scope in allowed_run_scopes]
    if not scopes or not any(output_root.parent.resolve() == scope for scope in scopes):
        raise ValueError("service output root must be an exact child of an allowed run scope")
    if output_root.exists():
        raise ValueError("refusing existing service output root")

    argv = build_launch_argv(python, launcher, Path(model_identity["model_path"]))
    command_payload = {
        "argv": argv,
        "environment": {
            "CUDA_VISIBLE_DEVICES": str(gpu_index),
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_OFFLINE": "1",
        },
    }
    command_sha = sha256_bytes(canonical_json_bytes(command_payload))
    output_root.mkdir(parents=False)
    log_path = output_root / "service.log"
    attempts_path = output_root / "readiness-attempts.jsonl"
    _atomic_create(attempts_path, b"")
    started_at = now()
    record = {
        "schema_version": "agentenhance.memgallery_naiverag_float32_service_record.v1",
        "status": "STARTING",
        "started_at": started_at,
        "release_receipt_sha256": sha256_bytes(release_bytes),
        "model_identity": model_identity,
        "gpu_index": gpu_index,
        "gpu_used_mib_before": gpu_used,
        "port": PORT,
        "scores_observed": 0,
    }
    _atomic_create(output_root / "service-record.json", json.dumps(record, indent=2, sort_keys=True).encode() + b"\n")
    _atomic_create(output_root / "command.json", json.dumps(command_payload, indent=2, sort_keys=True).encode() + b"\n")
    process: subprocess.Popen[bytes] | None = None
    log_handle = log_path.open("xb")
    try:
        environment = os.environ.copy()
        environment.update(command_payload["environment"])
        process = subprocess.Popen(
            argv,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=environment,
            start_new_session=True,
        )
        log_handle.close()
        pid = process.pid
        pgid = os.getpgid(pid)
        if pgid != pid:
            raise RuntimeError("service did not create an isolated process group")
        raw_cmdline = proc_cmdline(pid)
        accepted_response: bytes | None = None
        accepted_poll = 0
        for attempt in range(1, READINESS_ATTEMPTS + 1):
            if process.poll() is not None:
                raise RuntimeError(f"service exited before readiness with code {process.returncode}")
            started = time.monotonic()
            row: dict[str, Any] = {"attempt": attempt, "started_at": now()}
            try:
                request = urllib.request.Request(MODELS_ENDPOINT, method="GET")
                with urllib.request.urlopen(request, timeout=5) as response:
                    body = response.read(1024 * 1024 + 1)
                    row["http_status"] = response.status
                if len(body) > 1024 * 1024:
                    raise ValueError("models response exceeds one MiB")
                payload = json.loads(body)
                parse_models_response(payload)
                accepted_response = body
                accepted_poll = attempt
                row["status"] = "ACCEPTED"
                row["response_sha256"] = sha256_bytes(body)
            except Exception as exc:
                row["status"] = "WAITING"
                row["error_type"] = type(exc).__name__
                row["error"] = str(exc)
            row["wall_seconds"] = time.monotonic() - started
            _append_jsonl(attempts_path, row)
            if accepted_response is not None:
                break
            time.sleep(READINESS_INTERVAL_SECONDS)
        if accepted_response is None:
            raise RuntimeError("service did not become ready within the frozen polling window")
        models_path = output_root / "models-response.json"
        _atomic_create(models_path, accepted_response)
        ready = build_ready_receipt(
            pid=pid,
            pgid=pgid,
            cmdline_sha256=sha256_bytes(raw_cmdline),
            command_sha256=command_sha,
            models_response_sha256=sha256_bytes(accepted_response),
            model_identity=model_identity,
            release_receipt_sha256=sha256_bytes(release_bytes),
            gpu_index=gpu_index,
            gpu_used_mib_before=gpu_used,
            readiness_polls=accepted_poll,
            started_at=started_at,
        )
        _atomic_create(output_root / "service-ready.json", json.dumps(ready, indent=2, sort_keys=True).encode() + b"\n")
        _atomic_create(output_root / "READY_FOR_PARITY_PROBE", b"")
        return ready
    except Exception as exc:
        if not log_handle.closed:
            log_handle.close()
        stop_evidence: dict[str, Any] | None = None
        if process is not None and _process_exists(process.pid):
            try:
                stop_evidence = _terminate_owned_process(process.pid, timeout_seconds=30)
            except Exception as stop_exc:
                stop_evidence = {"stop_error_type": type(stop_exc).__name__, "stop_error": str(stop_exc)}
        failure = {
            "schema_version": "agentenhance.memgallery_naiverag_float32_service_failure.v1",
            "status": "TERMINAL_REJECTED",
            "started_at": started_at,
            "finished_at": now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "owned_process_stop": stop_evidence,
            "same_root_retry_allowed": False,
            "scores_observed": 0,
        }
        _atomic_create(output_root / "service-failure.json", json.dumps(failure, indent=2, sort_keys=True).encode() + b"\n")
        _write_terminal_inventory(
            output_root,
            (
                "service-record.json",
                "command.json",
                "readiness-attempts.jsonl",
                "service.log",
                "service-failure.json",
            ),
        )
        _atomic_create(output_root / "TERMINAL_REJECTED", b"")
        raise


def _write_terminal_inventory(root: Path, names: Sequence[str]) -> None:
    _atomic_create(
        root / "EVIDENCE_SHA256SUMS",
        "".join(f"{sha256_file(root / name)}  {name}\n" for name in names).encode(),
    )


def stop_service(service_root: Path) -> dict[str, Any]:
    root = probe_capture._validate_project_path(service_root, ("AgentEnhance", "runs"), "service_root")
    if not root.is_dir() or not (root / "READY_FOR_PARITY_PROBE").is_file():
        raise ValueError("service root is not ready for parity probe")
    if any((root / name).exists() for name in ("TERMINAL_ACCEPTED_STOPPED", "TERMINAL_REJECTED", "EVIDENCE_SHA256SUMS")):
        raise ValueError("service root is already terminal")
    ready, ready_bytes = _load_regular_json(root / "service-ready.json", "service-ready receipt")
    pid, pgid = validate_owned_process(ready)
    if os.getpgid(pid) != pgid:
        raise ValueError("live service process-group identity drift")
    stop_evidence = _terminate_owned_process(pid)
    require_port_free()
    stop = {
        "schema_version": "agentenhance.memgallery_naiverag_float32_service_stop.v1",
        "status": "TERMINAL_ACCEPTED_STOPPED",
        "stopped_at": now(),
        "pid": pid,
        "process_group_id": pgid,
        "service_ready_sha256": sha256_bytes(ready_bytes),
        **stop_evidence,
        "process_absent": not _process_exists(pid),
        "port_free": True,
        "scores_observed": 0,
    }
    _atomic_create(root / "service-stop.json", json.dumps(stop, indent=2, sort_keys=True).encode() + b"\n")
    _write_terminal_inventory(
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
    _atomic_create(root / "TERMINAL_ACCEPTED_STOPPED", b"")
    return stop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--output-root", type=Path, required=True)
    start.add_argument("--allowed-run-scope", type=Path, action="append", required=True)
    start.add_argument("--release-receipt", type=Path, required=True)
    start.add_argument("--model-path", type=Path, required=True)
    start.add_argument("--materialization-root", type=Path, required=True)
    start.add_argument("--prefetch-manifest", type=Path, required=True)
    start.add_argument("--launcher", type=Path, required=True)
    start.add_argument("--gpu-index", type=int, choices=ALLOWED_GPU_INDICES, required=True)
    stop = subparsers.add_parser("stop")
    stop.add_argument("--service-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "start":
        result = start_service(
            output_root=args.output_root,
            allowed_run_scopes=args.allowed_run_scope,
            release_receipt_path=args.release_receipt,
            model_path=args.model_path,
            materialization_root=args.materialization_root,
            prefetch_manifest=args.prefetch_manifest,
            launcher=args.launcher,
            gpu_index=args.gpu_index,
        )
    else:
        result = stop_service(args.service_root)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
