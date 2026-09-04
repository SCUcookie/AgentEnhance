#!/usr/bin/env python3
"""Compose direct capture, float32 endpoint capture, service stop, and parity audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import audit_memgallery_naiverag_encoder_parity as parity
import capture_memgallery_naiverag_encoder_probes as probe_capture
import manage_memgallery_naiverag_float32_service as service


CONTROLLER_NAME = "memgallery-naiverag-parity-controller-20260904-v1"
DIRECT_NAME = "memgallery-naiverag-direct-probe-20260904-v1"
SERVICE_NAME = "memgallery-naiverag-float32-service-20260904-v1"
ENDPOINT_NAME = "memgallery-naiverag-endpoint-probe-20260904-v1"
AUDIT_NAME = "memgallery-naiverag-parity-audit-20260904-v1"

SCRIPT_IDENTITIES = {
    "capture": (
        "capture_memgallery_naiverag_encoder_probes.py",
        "bcaa1b5f08949ff534e6fc722f1f5e76cb96a6c5bbc99a8b41c527cc4dab5ea5",
    ),
    "service": (
        "manage_memgallery_naiverag_float32_service.py",
        "6a4abb5bc1ef81ae4a76411ff29fc4f8e2f37fd96070eff0f51e8f893ecd21ad",
    ),
    "audit": (
        "audit_memgallery_naiverag_encoder_parity.py",
        "6d336d9aedfa03a4eb4c7945f120e755f60a10cd85022952be3930bdf9063609",
    ),
}


class StageFailure(RuntimeError):
    def __init__(self, stage: str, returncode: int):
        super().__init__(f"stage {stage} exited with code {returncode}")
        self.stage = stage
        self.returncode = returncode


def canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return probe_capture.sha256_file(path)


def now() -> str:
    return probe_capture.now()


def _atomic_create(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to replace existing controller evidence: {path}")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_script(path: Path, expected_name: str, expected_sha256: str) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.name != expected_name:
        raise ValueError(f"invalid lifecycle script path: {expected_name}")
    if sha256_file(path) != expected_sha256:
        raise ValueError(f"lifecycle script hash drift: {expected_name}")
    return path.resolve()


def resolve_scripts(script_root: Path) -> dict[str, Path]:
    if not script_root.is_absolute() or script_root.is_symlink() or not script_root.is_dir():
        raise ValueError("script root must be an absolute regular directory")
    resolved: dict[str, Path] = {}
    for role, (name, digest) in SCRIPT_IDENTITIES.items():
        resolved[role] = validate_script(script_root / name, name, digest)
    return resolved


def validate_run_scope(run_scope: Path) -> Path:
    resolved = probe_capture._validate_project_path(run_scope, ("AgentEnhance", "runs"), "run_scope")
    if not resolved.is_dir():
        raise ValueError("run scope must exist")
    expected = resolved.parts.index("AgentEnhance")
    if tuple(resolved.parts[expected + 1 :]) != ("runs",):
        raise ValueError("run scope must be the exact AgentEnhance/runs directory")
    return resolved


def lifecycle_roots(run_scope: Path) -> dict[str, Path]:
    return {
        "controller": run_scope / CONTROLLER_NAME,
        "direct": run_scope / DIRECT_NAME,
        "service": run_scope / SERVICE_NAME,
        "endpoint": run_scope / ENDPOINT_NAME,
        "audit": run_scope / AUDIT_NAME,
    }


def _default_runner(argv: Sequence[str], environment: Mapping[str, str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        list(argv),
        env=dict(environment),
        check=False,
        capture_output=True,
    )


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("ab") as handle:
        handle.write(canonical_json_bytes(dict(payload)))
        handle.flush()
        os.fsync(handle.fileno())


def execute_stage(
    stage: str,
    argv: Sequence[str],
    *,
    environment: Mapping[str, str],
    controller_root: Path,
    runner: Callable[[Sequence[str], Mapping[str, str]], subprocess.CompletedProcess[bytes]],
) -> dict[str, Any]:
    if not stage or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in stage):
        raise ValueError("unsafe stage name")
    started = now()
    completed = runner(tuple(argv), environment)
    stdout = bytes(completed.stdout or b"")
    stderr = bytes(completed.stderr or b"")
    stdout_name = f"{stage}.stdout"
    stderr_name = f"{stage}.stderr"
    _atomic_create(controller_root / stdout_name, stdout)
    _atomic_create(controller_root / stderr_name, stderr)
    record = {
        "schema_version": "agentenhance.memgallery_naiverag_parity_stage.v1",
        "stage": stage,
        "started_at": started,
        "finished_at": now(),
        "argv": list(argv),
        "environment": {
            key: environment[key]
            for key in ("CUDA_VISIBLE_DEVICES", "TRANSFORMERS_OFFLINE", "HF_HUB_OFFLINE")
            if key in environment
        },
        "returncode": completed.returncode,
        "stdout_sha256": sha256_bytes(stdout),
        "stdout_bytes": len(stdout),
        "stderr_sha256": sha256_bytes(stderr),
        "stderr_bytes": len(stderr),
        "attempts": 1,
        "retry_count": 0,
        "scores_observed": 0,
    }
    _append_jsonl(controller_root / "stages.jsonl", record)
    if completed.returncode != 0:
        raise StageFailure(stage, completed.returncode)
    return record


def _load_json(path: Path, label: str) -> dict[str, Any]:
    payload, _ = probe_capture._load_regular_json(path, label)
    return payload


def verify_inventory(root: Path, *, expected_members: int) -> str:
    inventory = root / "EVIDENCE_SHA256SUMS"
    if inventory.is_symlink() or not inventory.is_file():
        raise RuntimeError(f"missing evidence inventory: {root}")
    observed: set[str] = set()
    for line in inventory.read_text(encoding="utf-8").splitlines():
        pieces = line.split("  ", 1)
        if len(pieces) != 2 or len(pieces[0]) != 64 or any(
            char not in "0123456789abcdef" for char in pieces[0]
        ):
            raise RuntimeError(f"malformed evidence inventory: {root}")
        relative = Path(pieces[1])
        if relative.is_absolute() or ".." in relative.parts or pieces[1] in observed:
            raise RuntimeError(f"unsafe evidence inventory member: {root}")
        candidate = root / relative
        if candidate.is_symlink() or not candidate.is_file() or sha256_file(candidate) != pieces[0]:
            raise RuntimeError(f"evidence inventory hash drift: {candidate}")
        observed.add(pieces[1])
    if len(observed) != expected_members:
        raise RuntimeError(f"evidence inventory denominator drift: {root}")
    return sha256_file(inventory)


def _require_terminal_capture(root: Path, backend: str) -> dict[str, Any]:
    if not (root / "TERMINAL_ACCEPTED").is_file() or (root / "TERMINAL_REJECTED").exists():
        raise RuntimeError(f"{backend} capture root is not accepted")
    summary = _load_json(root / "capture-summary.json", f"{backend} capture summary")
    if (
        summary.get("status") != "TERMINAL_ACCEPTED"
        or summary.get("backend") != backend
        or summary.get("probe_count") != len(parity.PROBES)
        or summary.get("dimensions") != parity.DIMENSIONS
        or summary.get("scores_observed") != 0
    ):
        raise RuntimeError(f"{backend} capture summary drift")
    parity._validate_evidence(_load_json(root / "probe-evidence.json", f"{backend} probe evidence"), backend)
    verify_inventory(root, expected_members=3)
    return summary


def _require_stopped_service(root: Path) -> dict[str, Any]:
    if not (root / "TERMINAL_ACCEPTED_STOPPED").is_file() or (root / "TERMINAL_REJECTED").exists():
        raise RuntimeError("parity service is not terminal-accepted stopped")
    stop = _load_json(root / "service-stop.json", "service stop receipt")
    if (
        stop.get("status") != "TERMINAL_ACCEPTED_STOPPED"
        or stop.get("process_absent") is not True
        or stop.get("port_free") is not True
        or stop.get("scores_observed") != 0
    ):
        raise RuntimeError("service stop receipt drift")
    verify_inventory(root, expected_members=7)
    return stop


def _write_controller_inventory(root: Path, names: Sequence[str]) -> None:
    _atomic_create(
        root / "EVIDENCE_SHA256SUMS",
        "".join(f"{sha256_file(root / name)}  {name}\n" for name in names).encode(),
    )


def run_lifecycle(
    *,
    run_scope: Path,
    release_receipt: Path,
    model_path: Path,
    materialization_root: Path,
    prefetch_manifest: Path,
    launcher: Path,
    gpu_index: int,
    script_root: Path,
    runner: Callable[[Sequence[str], Mapping[str, str]], subprocess.CompletedProcess[bytes]] = _default_runner,
) -> dict[str, Any]:
    scope = validate_run_scope(run_scope)
    roots = lifecycle_roots(scope)
    collisions = [str(path) for path in roots.values() if path.exists() or path.is_symlink()]
    if collisions:
        raise ValueError(f"lifecycle root collision: {collisions[0]}")
    release_payload, release_bytes = probe_capture._load_regular_json(release_receipt, "Wave1 release receipt")
    service.validate_release_receipt(release_payload)
    scripts = resolve_scripts(script_root)
    launcher = service.validate_launcher(launcher)
    python = service.validate_python()
    if gpu_index not in service.ALLOWED_GPU_INDICES:
        raise ValueError("GPU index is outside the frozen project allocation")

    controller = roots["controller"]
    controller.mkdir(parents=False)
    _atomic_create(controller / "stages.jsonl", b"")
    started_at = now()
    record = {
        "schema_version": "agentenhance.memgallery_naiverag_parity_controller_record.v1",
        "status": "RUNNING",
        "started_at": started_at,
        "run_scope": str(scope),
        "roots": {key: str(value) for key, value in roots.items()},
        "release_receipt": str(release_receipt),
        "release_receipt_sha256": sha256_bytes(release_bytes),
        "model_path": str(model_path),
        "materialization_root": str(materialization_root),
        "prefetch_manifest": str(prefetch_manifest),
        "launcher": str(launcher),
        "gpu_index": gpu_index,
        "scripts": {role: {"path": str(path), "sha256": sha256_file(path)} for role, path in scripts.items()},
        "scores_observed": 0,
    }
    _atomic_create(controller / "controller-record.json", json.dumps(record, indent=2, sort_keys=True).encode() + b"\n")
    environment = os.environ.copy()
    environment.update(
        {
            "CUDA_VISIBLE_DEVICES": str(gpu_index),
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_OFFLINE": "1",
        }
    )
    emergency_cleanup_attempted = False
    cleanup: dict[str, Any] | None = None
    try:
        execute_stage(
            "direct_capture",
            (
                str(python), str(scripts["capture"]), "--backend", "official_direct_lmencoder",
                "--model-path", str(model_path), "--materialization-root", str(materialization_root),
                "--prefetch-manifest", str(prefetch_manifest), "--output-root", str(roots["direct"]),
                "--allowed-run-scope", str(scope),
            ),
            environment=environment,
            controller_root=controller,
            runner=runner,
        )
        _require_terminal_capture(roots["direct"], "official_direct_lmencoder")

        execute_stage(
            "service_start",
            (
                str(python), str(scripts["service"]), "start", "--output-root", str(roots["service"]),
                "--allowed-run-scope", str(scope), "--release-receipt", str(release_receipt),
                "--model-path", str(model_path), "--materialization-root", str(materialization_root),
                "--prefetch-manifest", str(prefetch_manifest), "--launcher", str(launcher),
                "--gpu-index", str(gpu_index),
            ),
            environment=environment,
            controller_root=controller,
            runner=runner,
        )
        if not (roots["service"] / "READY_FOR_PARITY_PROBE").is_file():
            raise RuntimeError("service start did not produce the ready marker")

        execute_stage(
            "endpoint_capture",
            (
                str(python), str(scripts["capture"]), "--backend", "vllm_openai_input",
                "--model-path", str(model_path), "--materialization-root", str(materialization_root),
                "--prefetch-manifest", str(prefetch_manifest),
                "--service-ready", str(roots["service"] / "service-ready.json"),
                "--endpoint", service.ENDPOINT, "--output-root", str(roots["endpoint"]),
                "--allowed-run-scope", str(scope),
            ),
            environment=environment,
            controller_root=controller,
            runner=runner,
        )
        _require_terminal_capture(roots["endpoint"], "vllm_openai_input")

        execute_stage(
            "service_stop",
            (str(python), str(scripts["service"]), "stop", "--service-root", str(roots["service"])),
            environment=environment,
            controller_root=controller,
            runner=runner,
        )
        _require_stopped_service(roots["service"])

        execute_stage(
            "parity_audit",
            (
                str(python), str(scripts["audit"]),
                "--direct", str(roots["direct"] / "probe-evidence.json"),
                "--endpoint", str(roots["endpoint"] / "probe-evidence.json"),
                "--output-root", str(roots["audit"]), "--allowed-run-scope", str(scope),
            ),
            environment=environment,
            controller_root=controller,
            runner=runner,
        )
        audit = _load_json(roots["audit"] / "parity-audit.json", "parity audit")
        if audit.get("decision") not in {"ENDPOINT_EQUIVALENT", "DIRECT_ENCODER_REQUIRED"}:
            raise RuntimeError("parity audit did not produce an accepted prospective decision")
        expected_status = f"TERMINAL_ACCEPTED_{audit['decision']}"
        if audit.get("status") != expected_status or not (roots["audit"] / expected_status).is_file():
            raise RuntimeError("parity audit terminal marker drift")
        verify_inventory(roots["audit"], expected_members=1)

        summary = {
            "schema_version": "agentenhance.memgallery_naiverag_parity_controller_summary.v1",
            "status": expected_status,
            "decision": audit["decision"],
            "started_at": started_at,
            "finished_at": now(),
            "stages_attempted": 5,
            "stages_accepted": 5,
            "service_stopped": True,
            "child_evidence": {
                key: {
                    "root": str(roots[key]),
                    "inventory_sha256": sha256_file(roots[key] / "EVIDENCE_SHA256SUMS"),
                }
                for key in ("direct", "service", "endpoint", "audit")
            },
            "parity_audit_sha256": sha256_file(roots["audit"] / "parity-audit.json"),
            "benchmark_examples_read": 0,
            "predictions_observed": 0,
            "scores_observed": 0,
            "official_values_used": False,
            "claim_eligible": False,
        }
        _atomic_create(controller / "controller-summary.json", json.dumps(summary, indent=2, sort_keys=True).encode() + b"\n")
        stage_names = [row for row in (controller / "stages.jsonl").read_text().splitlines() if row]
        output_names = ["controller-record.json", "stages.jsonl", "controller-summary.json"]
        for row in map(json.loads, stage_names):
            output_names.extend((f"{row['stage']}.stdout", f"{row['stage']}.stderr"))
        _write_controller_inventory(controller, output_names)
        _atomic_create(controller / expected_status, b"")
        return summary
    except Exception as exc:
        if (
            not emergency_cleanup_attempted
            and (roots["service"] / "READY_FOR_PARITY_PROBE").is_file()
            and not (roots["service"] / "TERMINAL_ACCEPTED_STOPPED").exists()
            and not (roots["service"] / "TERMINAL_REJECTED").exists()
        ):
            emergency_cleanup_attempted = True
            try:
                cleanup_record = execute_stage(
                    "failure_cleanup_service_stop",
                    (str(python), str(scripts["service"]), "stop", "--service-root", str(roots["service"])),
                    environment=environment,
                    controller_root=controller,
                    runner=runner,
                )
                _require_stopped_service(roots["service"])
                cleanup = {"status": "ACCEPTED", "stage": cleanup_record["stage"]}
            except Exception as cleanup_exc:
                cleanup = {
                    "status": "REJECTED",
                    "error_type": type(cleanup_exc).__name__,
                    "error": str(cleanup_exc),
                }
        failure = {
            "schema_version": "agentenhance.memgallery_naiverag_parity_controller_failure.v1",
            "status": "TERMINAL_REJECTED",
            "started_at": started_at,
            "finished_at": now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "service_cleanup": cleanup,
            "child_roots_retained": {key: path.exists() for key, path in roots.items() if key != "controller"},
            "same_root_retry_allowed": False,
            "scores_observed": 0,
            "official_values_used": False,
        }
        _atomic_create(controller / "controller-failure.json", json.dumps(failure, indent=2, sort_keys=True).encode() + b"\n")
        stage_rows = [json.loads(row) for row in (controller / "stages.jsonl").read_text().splitlines() if row]
        output_names = ["controller-record.json", "stages.jsonl", "controller-failure.json"]
        for row in stage_rows:
            output_names.extend((f"{row['stage']}.stdout", f"{row['stage']}.stderr"))
        _write_controller_inventory(controller, output_names)
        _atomic_create(controller / "TERMINAL_REJECTED", b"")
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-scope", type=Path, required=True)
    parser.add_argument("--release-receipt", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--materialization-root", type=Path, required=True)
    parser.add_argument("--prefetch-manifest", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--gpu-index", type=int, choices=service.ALLOWED_GPU_INDICES, required=True)
    parser.add_argument("--script-root", type=Path, default=Path(__file__).resolve().parent)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_lifecycle(
        run_scope=args.run_scope,
        release_receipt=args.release_receipt,
        model_path=args.model_path,
        materialization_root=args.materialization_root,
        prefetch_manifest=args.prefetch_manifest,
        launcher=args.launcher,
        gpu_index=args.gpu_index,
        script_root=args.script_root,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
