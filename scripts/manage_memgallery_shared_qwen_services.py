#!/usr/bin/env python3
"""Start and stop the protected shared Qwen services with signed evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

import manage_memgallery_naiverag_float32_service as release_gate


INFER_PYTHON = Path("/data1/anaconda3/envs/clo-infer/bin/python3.11")
READINESS_ATTEMPTS = 180
READINESS_INTERVAL_SECONDS = 5
STOP_TIMEOUT_SECONDS = 120
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_PREFLIGHT_GPU_USED_MIB = 100
ROLE_ORDER = ("chat", "embedding")
STOP_ORDER = tuple(reversed(ROLE_ORDER))
REQUIRED_GPU_INDICES = (1, 3, 4)

MODEL_SPECS = {
    "chat": {
        "model_id": "Qwen/Qwen3-VL-8B-Instruct",
        "revision": "5d854aab08710c16b980ec6d603d863b3821b915",
        "path": "/data1/2026/ldh/AgentEnhance/checkpoints/base-models/qwen3-vl-8b-instruct/rev-5d854aab08710c16b980ec6d603d863b3821b915",
        "manifest_sha256": "47a7e166264f2e2b10a9180c82cf3e2399157672eeba60d3bfe81d9bb49bac79",
        "inventory_sha256": "a9246eb726bbc0f09a388d27a989a5c1c483915508ee38cb8b1c41e435914dbb",
        "files": 18,
        "bytes": 17545916927,
    },
    "embedding": {
        "model_id": "Qwen/Qwen3-VL-Embedding-2B",
        "revision": "c35dddf20620fe32745cb3d01f87ba64ae316313",
        "path": "/data1/2026/ldh/AgentEnhance/checkpoints/base-models/qwen3-vl-embedding-2b/rev-c35dddf20620fe32745cb3d01f87ba64ae316313",
        "manifest_sha256": "f8768171271284a4e032c5fc82f1d8624007195c66dfebd40765c9e39b7ec10f",
        "inventory_sha256": "7c91bdd2cdf46e9f0e112bcf3f1dcc45a35076e1543ab109629ca57d665f5b33",
        "files": 20,
        "bytes": 4271069478,
    },
}

SERVICE_SPECS = {
    "chat": {
        "served_model": "Qwen3-VL-8B-Instruct",
        "port": 18320,
        "endpoint": "http://127.0.0.1:18320/v1/chat/completions",
        "models_endpoint": "http://127.0.0.1:18320/v1/models",
        "gpu_indices": (3, 4),
    },
    "embedding": {
        "served_model": "Qwen3-VL-Embedding-2B",
        "port": 18321,
        "endpoint": "http://127.0.0.1:18321/v1/embeddings",
        "models_endpoint": "http://127.0.0.1:18321/v1/models",
        "gpu_indices": (1,),
    },
}


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
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def now() -> str:
    return release_gate.now()


def _atomic_create(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to replace existing shared-service evidence: {path}")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _load_regular_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be an absolute regular non-symlink file")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload, raw


def _validate_output_root(output_root: Path, allowed_run_scopes: Sequence[Path]) -> None:
    if not output_root.is_absolute() or output_root.is_symlink():
        raise ValueError("service output root must be absolute and not a symlink")
    scopes: list[Path] = []
    for scope in allowed_run_scopes:
        if not scope.is_absolute() or scope.is_symlink() or not scope.is_dir():
            raise ValueError("allowed run scope must be an absolute regular directory")
        resolved = scope.resolve()
        parts = resolved.parts
        indices = [index for index, value in enumerate(parts) if value == "AgentEnhance"]
        if len(indices) != 1 or tuple(parts[indices[0] + 1 :]) != ("runs",):
            raise ValueError("allowed run scope must be the exact AgentEnhance/runs directory")
        scopes.append(resolved)
    if not scopes or not any(output_root.parent.resolve() == scope for scope in scopes):
        raise ValueError("service output root must be an exact child of an allowed run scope")
    if output_root.exists():
        raise ValueError("refusing existing service output root")


def validate_python(path: Path = INFER_PYTHON) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("inference Python is not the exact executable regular file")
    if path.resolve() != INFER_PYTHON:
        raise ValueError("inference Python path drift")
    return path.resolve()


def _safe_inventory_name(raw: str) -> str:
    name = raw.lstrip("*")
    candidate = Path(name)
    if not name or candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != name:
        raise ValueError("unsafe model inventory member")
    return name


def validate_model_snapshot(role: str, model_path: Path) -> dict[str, Any]:
    if role not in MODEL_SPECS:
        raise ValueError(f"unknown model role: {role}")
    spec = MODEL_SPECS[role]
    expected_path = Path(str(spec["path"]))
    if model_path != expected_path or not model_path.is_absolute() or model_path.is_symlink() or not model_path.is_dir():
        raise ValueError(f"{role} model path drift")
    root = model_path.resolve(strict=True)
    if root != expected_path:
        raise ValueError(f"{role} model resolved path drift")
    manifest_path = root / "placement-manifest.json"
    inventory_path = root / "MODEL_FILES_SHA256SUMS"
    manifest, manifest_bytes = _load_regular_json(manifest_path, f"{role} placement manifest")
    if sha256_bytes(manifest_bytes) != spec["manifest_sha256"]:
        raise ValueError(f"{role} placement manifest hash drift")
    if inventory_path.is_symlink() or not inventory_path.is_file():
        raise ValueError(f"{role} model inventory is missing or linked")
    if sha256_file(inventory_path) != spec["inventory_sha256"]:
        raise ValueError(f"{role} model inventory hash drift")
    expected_manifest = {
        "schema_version": "model_placement_manifest.v1",
        "model_id": spec["model_id"],
        "revision": spec["revision"],
        "file_count": spec["files"],
        "total_bytes": spec["bytes"],
        "model_files_inventory_sha256": spec["inventory_sha256"],
        "read_only_after_publish": True,
    }
    for field, value in expected_manifest.items():
        if manifest.get(field) != value:
            raise ValueError(f"{role} placement manifest drift: {field}")

    observed: set[str] = set()
    total_bytes = 0
    for line in inventory_path.read_text(encoding="utf-8").splitlines():
        pieces = line.split(maxsplit=1)
        if len(pieces) != 2 or not _is_sha256(pieces[0]):
            raise ValueError(f"{role} model inventory is malformed")
        name = _safe_inventory_name(pieces[1])
        if name in observed:
            raise ValueError(f"{role} model inventory contains duplicates")
        candidate = root / name
        if candidate.is_symlink() or not candidate.is_file() or candidate.resolve(strict=True) != candidate:
            raise ValueError(f"{role} model inventory member is missing or linked: {name}")
        if sha256_file(candidate) != pieces[0]:
            raise ValueError(f"{role} model file hash drift: {name}")
        observed.add(name)
        total_bytes += candidate.stat().st_size
    if len(observed) != spec["files"] or total_bytes != spec["bytes"]:
        raise ValueError(f"{role} model snapshot denominator drift")
    all_files: set[str] = set()
    for candidate in root.rglob("*"):
        if candidate.is_symlink():
            raise ValueError(f"{role} model snapshot contains a symlink")
        if candidate.is_file():
            all_files.add(candidate.relative_to(root).as_posix())
    if all_files != observed | {"placement-manifest.json", "MODEL_FILES_SHA256SUMS"}:
        raise ValueError(f"{role} model snapshot file surface drift")
    identity = {
        "role": role,
        "model_id": spec["model_id"],
        "revision": spec["revision"],
        "model_path": str(root),
        "placement_manifest_sha256": spec["manifest_sha256"],
        "model_inventory_sha256": spec["inventory_sha256"],
        "model_files": spec["files"],
        "model_bytes": spec["bytes"],
    }
    identity["model_snapshot_sha256"] = sha256_bytes(canonical_json_bytes(identity))
    return identity


def build_launch_argv(role: str, python: Path, model_path: Path) -> list[str]:
    if role not in SERVICE_SPECS:
        raise ValueError(f"unknown service role: {role}")
    spec = SERVICE_SPECS[role]
    base = [
        str(python), "-m", "vllm.entrypoints.openai.api_server",
        "--host", "127.0.0.1", "--port", str(spec["port"]),
        "--model", str(model_path), "--served-model-name", str(spec["served_model"]),
        "--dtype", "bfloat16",
    ]
    if role == "chat":
        return base + [
            "--tensor-parallel-size", "2", "--max-model-len", "32768",
            "--gpu-memory-utilization", "0.90", "--max-num-seqs", "1",
            "--limit-mm-per-prompt", '{"image":21,"video":0}', "--trust-remote-code",
        ]
    return base + [
        "--runner", "pooling", "--convert", "embed", "--tensor-parallel-size", "1",
        "--max-model-len", "8192", "--gpu-memory-utilization", "0.90", "--max-num-seqs", "8",
        "--hf-overrides", '{"is_matryoshka":true}',
        "--pooler-config", '{"dimensions":1024,"normalize":true}',
        "--limit-mm-per-prompt", '{"image":1,"video":0}', "--trust-remote-code",
    ]


def parse_gpu_table(output: str) -> dict[int, int]:
    observed: dict[int, int] = {}
    for line in output.splitlines():
        pieces = [piece.strip() for piece in line.split(",")]
        if len(pieces) != 2:
            raise ValueError("malformed nvidia-smi output")
        try:
            index, used = int(pieces[0]), int(pieces[1])
        except ValueError as exc:
            raise ValueError("nonnumeric nvidia-smi output") from exc
        if index in observed:
            raise ValueError("duplicate GPU observation")
        observed[index] = used
    if any(index not in observed for index in REQUIRED_GPU_INDICES):
        raise ValueError("required GPU was not observed exactly once")
    return {index: observed[index] for index in REQUIRED_GPU_INDICES}


def observe_gpu_headroom() -> dict[int, int]:
    completed = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"],
        check=True, capture_output=True, text=True,
    )
    observed = parse_gpu_table(completed.stdout)
    busy = {index: used for index, used in observed.items() if used > MAX_PREFLIGHT_GPU_USED_MIB}
    if busy:
        index = sorted(busy)[0]
        raise RuntimeError(f"GPU {index} is not free enough: {busy[index]} MiB")
    return observed


def require_ports_free() -> None:
    for role in ROLE_ORDER:
        port = int(SERVICE_SPECS[role]["port"])
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            try:
                candidate.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"shared-service port {port} is not free") from exc


def parse_models_response(role: str, payload: object) -> None:
    if role not in SERVICE_SPECS:
        raise ValueError(f"unknown service role: {role}")
    if not isinstance(payload, Mapping) or payload.get("object") != "list":
        raise ValueError(f"{role} models response is not an OpenAI list")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
        raise ValueError(f"{role} models response cardinality drift")
    if data[0].get("id") != SERVICE_SPECS[role]["served_model"] or data[0].get("object") != "model":
        raise ValueError(f"{role} models response identity drift")


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def parse_chat_smoke(payload: object) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("chat smoke response must be an object")
    choices, usage = payload.get("choices"), payload.get("usage")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
        raise ValueError("chat smoke choice cardinality drift")
    message = choices[0].get("message")
    if not isinstance(message, Mapping) or not isinstance(message.get("content"), str) or not message["content"].strip():
        raise ValueError("chat smoke response lacks nonempty content")
    if not isinstance(usage, Mapping):
        raise ValueError("chat smoke response lacks usage")
    prompt = _nonnegative_int(usage.get("prompt_tokens"), "chat prompt_tokens")
    completion = _nonnegative_int(usage.get("completion_tokens"), "chat completion_tokens")
    total = _nonnegative_int(usage.get("total_tokens"), "chat total_tokens")
    if prompt + completion != total:
        raise ValueError("chat smoke usage does not sum")
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


def parse_embedding_smoke(payload: object) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("model") != SERVICE_SPECS["embedding"]["served_model"]:
        raise ValueError("embedding smoke model identity drift")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping) or data[0].get("index") != 0:
        raise ValueError("embedding smoke item cardinality/order drift")
    vector = data[0].get("embedding")
    if not isinstance(vector, list) or len(vector) != 1024:
        raise ValueError("embedding smoke dimension drift")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
        raise ValueError("embedding smoke contains a nonnumeric value")
    values = [float(value) for value in vector]
    norm = math.sqrt(sum(value * value for value in values))
    if not all(math.isfinite(value) for value in values) or not math.isfinite(norm) or norm == 0.0:
        raise ValueError("embedding smoke vector is nonfinite or zero")
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        raise ValueError("embedding smoke response lacks usage")
    prompt = _nonnegative_int(usage.get("prompt_tokens"), "embedding prompt_tokens")
    total = _nonnegative_int(usage.get("total_tokens"), "embedding total_tokens")
    if prompt != total:
        raise ValueError("embedding smoke usage does not sum")
    return {"dimensions": 1024, "prompt_tokens": prompt, "total_tokens": total}


def proc_cmdline(pid: int, proc_root: Path = Path("/proc")) -> bytes:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        raise ValueError("invalid service PID")
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError) as exc:
        raise RuntimeError("owned service process is not observable") from exc
    if not raw:
        raise RuntimeError("owned service process has an empty command line")
    return raw


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def validate_owned_process(process: Mapping[str, Any], proc_root: Path = Path("/proc")) -> tuple[int, int]:
    pid, pgid = process.get("pid"), process.get("process_group_id")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1 or pgid != pid:
        raise ValueError("service PID/process-group identity drift")
    if sha256_bytes(proc_cmdline(pid, proc_root)) != process.get("cmdline_sha256"):
        raise ValueError("owned service command-line identity drift")
    return pid, pgid


def _terminate_pid(pid: int, *, timeout_seconds: int = STOP_TIMEOUT_SECONDS) -> dict[str, Any]:
    if not _process_exists(pid):
        return {"already_absent": True, "sigterm_sent": False, "sigkill_sent": False}
    os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            return {"already_absent": False, "sigterm_sent": True, "sigkill_sent": False}
        time.sleep(1)
    os.killpg(pid, signal.SIGKILL)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            return {"already_absent": False, "sigterm_sent": True, "sigkill_sent": True}
        time.sleep(1)
    raise RuntimeError("owned service process group did not stop")


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("ab") as handle:
        handle.write(canonical_json_bytes(dict(payload)))
        handle.flush()
        os.fsync(handle.fileno())


def _http_json(url: str, *, request_payload: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], bytes]:
    body = None if request_payload is None else canonical_json_bytes(request_payload)
    headers = {} if body is None else {"Authorization": "Bearer EMPTY", "Content-Type": "application/json"}
    request = urllib.request.Request(url, data=body, headers=headers, method="GET" if body is None else "POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise ValueError(f"service returned HTTP status {response.status!r}")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("service response is empty or exceeds byte ceiling")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("service returned invalid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("service response must be a JSON object")
    return payload, raw


def _smoke_request(role: str) -> dict[str, Any]:
    if role == "chat":
        return {
            "model": SERVICE_SPECS[role]["served_model"],
            "temperature": 0.0,
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "Return exactly READY."}],
        }
    return {
        "model": SERVICE_SPECS[role]["served_model"],
        "input": ["service health check"],
        "encoding_format": "float",
    }


def _write_inventory(root: Path, names: Sequence[str]) -> None:
    _atomic_create(
        root / "EVIDENCE_SHA256SUMS",
        "".join(f"{sha256_file(root / name)}  {name}\n" for name in names).encode("utf-8"),
    )


def _existing_evidence_names(root: Path, candidates: Sequence[str]) -> list[str]:
    return [name for name in candidates if (root / name).is_file() and not (root / name).is_symlink()]


def validate_ready_receipt(root: Path, ready: Mapping[str, Any]) -> Mapping[str, Any]:
    if (
        ready.get("schema_version") != "agentenhance.memgallery_shared_qwen_service_ready.v1"
        or ready.get("status") != "READY_FOR_MEMGALLERY"
        or ready.get("automatic_retries") != 0
        or ready.get("benchmark_examples_read") != 0
        or ready.get("predictions_observed") != 0
        or ready.get("scores_observed") != 0
    ):
        raise ValueError("shared service ready receipt drift")
    models = ready.get("models")
    services = ready.get("services")
    if not isinstance(models, Mapping) or set(models) != set(ROLE_ORDER):
        raise ValueError("shared service model surface drift")
    if not isinstance(services, Mapping) or set(services) != set(ROLE_ORDER):
        raise ValueError("shared service role surface drift")
    commands, _ = _load_regular_json(root / "commands.json", "shared service commands")
    if set(commands) != set(ROLE_ORDER):
        raise ValueError("shared service command surface drift")
    for role in ROLE_ORDER:
        model = models[role]
        expected_model = MODEL_SPECS[role]
        if not isinstance(model, Mapping):
            raise ValueError(f"{role} model identity is not an object")
        expected_fields = {
            "role": role,
            "model_id": expected_model["model_id"],
            "revision": expected_model["revision"],
            "model_path": expected_model["path"],
            "placement_manifest_sha256": expected_model["manifest_sha256"],
            "model_inventory_sha256": expected_model["inventory_sha256"],
            "model_files": expected_model["files"],
            "model_bytes": expected_model["bytes"],
        }
        if any(model.get(field) != value for field, value in expected_fields.items()):
            raise ValueError(f"{role} ready model identity drift")
        if not _is_sha256(model.get("model_snapshot_sha256")):
            raise ValueError(f"{role} ready model snapshot hash is invalid")

        process = services[role]
        spec = SERVICE_SPECS[role]
        if not isinstance(process, Mapping):
            raise ValueError(f"{role} service identity is not an object")
        for field in ("served_model", "port", "endpoint", "models_endpoint"):
            if process.get(field) != spec[field]:
                raise ValueError(f"{role} service identity drift: {field}")
        if process.get("gpu_indices") != list(spec["gpu_indices"]):
            raise ValueError(f"{role} GPU identity drift")
        if not isinstance(process.get("readiness_polls"), int) or not 1 <= process["readiness_polls"] <= READINESS_ATTEMPTS:
            raise ValueError(f"{role} readiness poll count drift")
        for field in ("cmdline_sha256", "command_sha256", "models_response_sha256"):
            if not _is_sha256(process.get(field)):
                raise ValueError(f"{role} service hash is invalid: {field}")
        expected_command = {
            "argv": build_launch_argv(role, INFER_PYTHON, Path(str(model["model_path"]))),
            "environment": {
                "CUDA_VISIBLE_DEVICES": ",".join(str(index) for index in spec["gpu_indices"]),
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_OFFLINE": "1",
            },
        }
        if commands[role] != expected_command:
            raise ValueError(f"{role} command identity drift")
        if sha256_bytes(canonical_json_bytes(commands[role])) != process["command_sha256"]:
            raise ValueError(f"{role} command hash drift")

        models_path = root / f"{role}-models-response.json"
        smoke_path = root / f"{role}-smoke-response.json"
        models_payload, models_raw = _load_regular_json(models_path, f"{role} models response")
        smoke_payload, smoke_raw = _load_regular_json(smoke_path, f"{role} smoke response")
        if sha256_bytes(models_raw) != process["models_response_sha256"]:
            raise ValueError(f"{role} models response hash drift")
        parse_models_response(role, models_payload)
        smoke = process.get("smoke")
        if not isinstance(smoke, Mapping):
            raise ValueError(f"{role} smoke evidence is not an object")
        expected_request_sha = sha256_bytes(canonical_json_bytes(_smoke_request(role)))
        if (
            smoke.get("request_sha256") != expected_request_sha
            or smoke.get("response_sha256") != sha256_bytes(smoke_raw)
            or smoke.get("response_bytes") != len(smoke_raw)
            or smoke.get("attempts") != 1
            or smoke.get("retry_count") != 0
        ):
            raise ValueError(f"{role} smoke evidence drift")
        if role == "chat":
            parse_chat_smoke(smoke_payload)
        else:
            parse_embedding_smoke(smoke_payload)
    return services


def start_services(
    *,
    output_root: Path,
    allowed_run_scopes: Sequence[Path],
    release_receipt_path: Path,
    chat_model_path: Path,
    embedding_model_path: Path,
) -> dict[str, Any]:
    release, release_bytes = _load_regular_json(release_receipt_path, "Wave1 release receipt")
    release_gate.validate_release_receipt(release)
    _validate_output_root(output_root, allowed_run_scopes)
    models = {
        "chat": validate_model_snapshot("chat", chat_model_path),
        "embedding": validate_model_snapshot("embedding", embedding_model_path),
    }
    python = validate_python()
    gpu_used = observe_gpu_headroom()
    require_ports_free()

    commands: dict[str, Any] = {}
    for role in ROLE_ORDER:
        spec = SERVICE_SPECS[role]
        argv = build_launch_argv(role, python, Path(models[role]["model_path"]))
        commands[role] = {
            "argv": argv,
            "environment": {
                "CUDA_VISIBLE_DEVICES": ",".join(str(index) for index in spec["gpu_indices"]),
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_OFFLINE": "1",
            },
        }

    output_root.mkdir(parents=False)
    started_at = now()
    record = {
        "schema_version": "agentenhance.memgallery_shared_qwen_service_record.v1",
        "status": "STARTING",
        "started_at": started_at,
        "release_receipt_sha256": sha256_bytes(release_bytes),
        "models": models,
        "gpu_used_mib_before": {str(key): value for key, value in gpu_used.items()},
        "scores_observed": 0,
    }
    _atomic_create(output_root / "service-record.json", json.dumps(record, indent=2, sort_keys=True).encode() + b"\n")
    _atomic_create(output_root / "commands.json", json.dumps(commands, indent=2, sort_keys=True).encode() + b"\n")
    for role in ROLE_ORDER:
        _atomic_create(output_root / f"{role}-readiness-attempts.jsonl", b"")

    processes: dict[str, subprocess.Popen[bytes]] = {}
    process_records: dict[str, dict[str, Any]] = {}
    logs: dict[str, Any] = {}
    durable_candidates = [
        "service-record.json", "commands.json",
        "chat-readiness-attempts.jsonl", "embedding-readiness-attempts.jsonl",
        "chat-models-response.json", "embedding-models-response.json",
        "chat-smoke-response.json", "embedding-smoke-response.json",
        "service-ready.json", "chat.log", "embedding.log",
    ]
    try:
        for role in ROLE_ORDER:
            logs[role] = (output_root / f"{role}.log").open("xb")
            environment = os.environ.copy()
            environment.update(commands[role]["environment"])
            process = subprocess.Popen(
                commands[role]["argv"], stdout=logs[role], stderr=subprocess.STDOUT,
                env=environment, start_new_session=True,
            )
            processes[role] = process
            pid = process.pid
            pgid = os.getpgid(pid)
            if pgid != pid:
                raise RuntimeError(f"{role} service did not create an isolated process group")
            process_records[role] = {
                "pid": pid,
                "process_group_id": pgid,
                "cmdline_sha256": sha256_bytes(proc_cmdline(pid)),
                "command_sha256": sha256_bytes(canonical_json_bytes(commands[role])),
            }
        for handle in logs.values():
            handle.close()

        model_responses: dict[str, bytes] = {}
        readiness_polls: dict[str, int] = {}
        for role in ROLE_ORDER:
            attempts_path = output_root / f"{role}-readiness-attempts.jsonl"
            for attempt in range(1, READINESS_ATTEMPTS + 1):
                for process_role, process in processes.items():
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"{process_role} service exited before readiness with code {process.returncode}"
                        )
                started = time.monotonic()
                row: dict[str, Any] = {"attempt": attempt, "started_at": now()}
                try:
                    payload, raw = _http_json(str(SERVICE_SPECS[role]["models_endpoint"]))
                    parse_models_response(role, payload)
                    model_responses[role] = raw
                    readiness_polls[role] = attempt
                    row.update({"status": "ACCEPTED", "response_sha256": sha256_bytes(raw)})
                except Exception as exc:
                    row.update({"status": "WAITING", "error_type": type(exc).__name__, "error": str(exc)})
                row["wall_seconds"] = time.monotonic() - started
                _append_jsonl(attempts_path, row)
                if role in model_responses:
                    break
                time.sleep(READINESS_INTERVAL_SECONDS)
            if role not in model_responses:
                raise RuntimeError(f"{role} service did not become ready within the frozen polling window")

        smoke_responses: dict[str, bytes] = {}
        smoke_evidence: dict[str, Any] = {}
        for role in ROLE_ORDER:
            request = _smoke_request(role)
            payload, raw = _http_json(str(SERVICE_SPECS[role]["endpoint"]), request_payload=request)
            parsed = parse_chat_smoke(payload) if role == "chat" else parse_embedding_smoke(payload)
            smoke_responses[role] = raw
            smoke_evidence[role] = {
                "request_sha256": sha256_bytes(canonical_json_bytes(request)),
                "response_sha256": sha256_bytes(raw),
                "response_bytes": len(raw),
                "attempts": 1,
                "retry_count": 0,
                **parsed,
            }

        for role in ROLE_ORDER:
            _atomic_create(output_root / f"{role}-models-response.json", model_responses[role])
            _atomic_create(output_root / f"{role}-smoke-response.json", smoke_responses[role])
        ready = {
            "schema_version": "agentenhance.memgallery_shared_qwen_service_ready.v1",
            "status": "READY_FOR_MEMGALLERY",
            "started_at": started_at,
            "ready_at": now(),
            "release_receipt_sha256": sha256_bytes(release_bytes),
            "models": models,
            "services": {
                role: {
                    **SERVICE_SPECS[role],
                    "gpu_indices": list(SERVICE_SPECS[role]["gpu_indices"]),
                    **process_records[role],
                    "models_response_sha256": sha256_bytes(model_responses[role]),
                    "readiness_polls": readiness_polls[role],
                    "smoke": smoke_evidence[role],
                }
                for role in ROLE_ORDER
            },
            "automatic_retries": 0,
            "benchmark_examples_read": 0,
            "predictions_observed": 0,
            "scores_observed": 0,
        }
        _atomic_create(output_root / "service-ready.json", json.dumps(ready, indent=2, sort_keys=True).encode() + b"\n")
        _atomic_create(output_root / "READY_FOR_MEMGALLERY", b"")
        return ready
    except Exception as exc:
        for handle in logs.values():
            if not handle.closed:
                handle.close()
        cleanup: dict[str, Any] = {}
        for role in STOP_ORDER:
            process = processes.get(role)
            if process is None:
                continue
            try:
                current_pgid = os.getpgid(process.pid) if _process_exists(process.pid) else process.pid
                if current_pgid != process.pid:
                    raise ValueError("startup cleanup process-group identity drift")
                if _process_exists(process.pid):
                    expected = process_records.get(role, {}).get("cmdline_sha256")
                    if expected is None or sha256_bytes(proc_cmdline(process.pid)) != expected:
                        raise ValueError("startup cleanup command-line identity drift")
                cleanup[role] = {"status": "ACCEPTED", **_terminate_pid(process.pid, timeout_seconds=30)}
            except Exception as cleanup_exc:
                cleanup[role] = {
                    "status": "REJECTED", "error_type": type(cleanup_exc).__name__, "error": str(cleanup_exc)
                }
        failure = {
            "schema_version": "agentenhance.memgallery_shared_qwen_service_failure.v1",
            "status": "TERMINAL_REJECTED",
            "started_at": started_at,
            "finished_at": now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "owned_process_cleanup": cleanup,
            "same_root_retry_allowed": False,
            "scores_observed": 0,
        }
        _atomic_create(output_root / "service-failure.json", json.dumps(failure, indent=2, sort_keys=True).encode() + b"\n")
        names = _existing_evidence_names(output_root, durable_candidates) + ["service-failure.json"]
        _write_inventory(output_root, names)
        _atomic_create(output_root / "TERMINAL_REJECTED", b"")
        raise


def _validate_service_root(service_root: Path) -> Path:
    if not service_root.is_absolute() or service_root.is_symlink() or not service_root.is_dir():
        raise ValueError("shared service root must be an absolute regular directory")
    root = service_root.resolve()
    parts = root.parts
    indices = [index for index, value in enumerate(parts) if value == "AgentEnhance"]
    if len(indices) != 1 or tuple(parts[indices[0] + 1 : indices[0] + 2]) != ("runs",) or len(parts) != indices[0] + 3:
        raise ValueError("shared service root must be an exact child of AgentEnhance/runs")
    return root


def stop_services(service_root: Path) -> dict[str, Any]:
    root = _validate_service_root(service_root)
    if not (root / "READY_FOR_MEMGALLERY").is_file():
        raise ValueError("shared service root is not ready")
    if any((root / name).exists() for name in ("TERMINAL_ACCEPTED_STOPPED", "TERMINAL_REJECTED", "EVIDENCE_SHA256SUMS")):
        raise ValueError("shared service root is already terminal")
    ready, ready_bytes = _load_regular_json(root / "service-ready.json", "shared service ready receipt")
    services = validate_ready_receipt(root, ready)

    outcomes: dict[str, Any] = {}
    errors: dict[str, Any] = {}
    for role in STOP_ORDER:
        try:
            process = services[role]
            if process.get("port") != SERVICE_SPECS[role]["port"] or process.get("endpoint") != SERVICE_SPECS[role]["endpoint"]:
                raise ValueError(f"{role} service endpoint identity drift")
            pid = process.get("pid")
            if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
                raise ValueError(f"{role} service PID drift")
            if _process_exists(pid):
                validated_pid, pgid = validate_owned_process(process)
                if os.getpgid(validated_pid) != pgid:
                    raise ValueError(f"{role} live process-group identity drift")
            outcomes[role] = _terminate_pid(pid)
            if _process_exists(pid):
                raise RuntimeError(f"{role} process remains after stop")
        except Exception as exc:
            errors[role] = {"error_type": type(exc).__name__, "error": str(exc)}
    try:
        require_ports_free()
    except Exception as exc:
        errors["ports"] = {"error_type": type(exc).__name__, "error": str(exc)}
    if errors:
        failure = {
            "schema_version": "agentenhance.memgallery_shared_qwen_service_stop_failure.v1",
            "status": "TERMINAL_REJECTED",
            "stopped_at": now(),
            "service_ready_sha256": sha256_bytes(ready_bytes),
            "outcomes": outcomes,
            "errors": errors,
            "same_root_retry_allowed": False,
            "scores_observed": 0,
        }
        _atomic_create(root / "service-stop-failure.json", json.dumps(failure, indent=2, sort_keys=True).encode() + b"\n")
        base = [
            "service-record.json", "commands.json",
            "chat-readiness-attempts.jsonl", "embedding-readiness-attempts.jsonl",
            "chat-models-response.json", "embedding-models-response.json",
            "chat-smoke-response.json", "embedding-smoke-response.json",
            "service-ready.json", "chat.log", "embedding.log", "service-stop-failure.json",
        ]
        _write_inventory(root, base)
        _atomic_create(root / "TERMINAL_REJECTED", b"")
        raise RuntimeError(f"shared service stop failed: {sorted(errors)}")
    stop = {
        "schema_version": "agentenhance.memgallery_shared_qwen_service_stop.v1",
        "status": "TERMINAL_ACCEPTED_STOPPED",
        "stopped_at": now(),
        "service_ready_sha256": sha256_bytes(ready_bytes),
        "outcomes": outcomes,
        "processes_absent": True,
        "ports_free": True,
        "scores_observed": 0,
    }
    _atomic_create(root / "service-stop.json", json.dumps(stop, indent=2, sort_keys=True).encode() + b"\n")
    names = [
        "service-record.json", "commands.json",
        "chat-readiness-attempts.jsonl", "embedding-readiness-attempts.jsonl",
        "chat-models-response.json", "embedding-models-response.json",
        "chat-smoke-response.json", "embedding-smoke-response.json",
        "service-ready.json", "chat.log", "embedding.log", "service-stop.json",
    ]
    _write_inventory(root, names)
    _atomic_create(root / "TERMINAL_ACCEPTED_STOPPED", b"")
    return stop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--output-root", type=Path, required=True)
    start.add_argument("--allowed-run-scope", type=Path, action="append", required=True)
    start.add_argument("--release-receipt", type=Path, required=True)
    start.add_argument("--chat-model-path", type=Path, default=Path(MODEL_SPECS["chat"]["path"]))
    start.add_argument("--embedding-model-path", type=Path, default=Path(MODEL_SPECS["embedding"]["path"]))
    stop = subparsers.add_parser("stop")
    stop.add_argument("--service-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "start":
        result = start_services(
            output_root=args.output_root,
            allowed_run_scopes=args.allowed_run_scope,
            release_receipt_path=args.release_receipt,
            chat_model_path=args.chat_model_path,
            embedding_model_path=args.embedding_model_path,
        )
    else:
        result = stop_services(args.service_root)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
