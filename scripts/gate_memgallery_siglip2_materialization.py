#!/usr/bin/env python3
"""Fail-closed preflight and launcher for the frozen Mem-Gallery SigLIP2 snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable


EXPECTED_REPOSITORY = "google/siglip2-base-patch16-384"
EXPECTED_REVISION = "f775b65a79762255128c981547af89addcfe0f88"
EXPECTED_TARGET_SUFFIX = "cache/models/memgallery-vmem-siglip2-base-patch16-384-20260904-v1"
EXPECTED_INTEGRITY = {
    "repository": "Ethan-Bei/Mem-Gallery",
    "revision": "af912daba984e896e253016b7c7e334ef92c2a6f",
    "files": 1515,
    "bytes": 545845389,
    "dialog_files": 20,
    "image_files": 1490,
    "questions": 1711,
}
BLOCKED_PROCESS_TOKENS = (
    "remote_wma_wave1_controller",
    "remote_wma_full_method",
    "run_wma_seeded.py",
    "vllm.entrypoints.openai.api_server",
)
BLOCKED_PORTS = frozenset({18113, 18114, 18120, 18220, 18221, 18222})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_remote_root(path: Path) -> Path:
    if not path.is_absolute() or path.name != "AgentEnhance" or path.is_symlink():
        raise RuntimeError("remote root must be an absolute non-symlink AgentEnhance directory")
    if len(path.parts) < 2 or path.parts[1] not in {"data1", "data2"}:
        raise RuntimeError("remote root must be below /data1 or /data2")
    return path


def verify_inventory(root: Path) -> int:
    sums = root / "EVIDENCE_SHA256SUMS"
    if not sums.is_file() or sums.is_symlink():
        raise RuntimeError("dataset integrity evidence inventory is missing or symlinked")
    count = 0
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        if "  " not in line:
            raise RuntimeError("malformed dataset integrity evidence inventory")
        expected, raw_path = line.split("  ", 1)
        if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
            raise RuntimeError("invalid dataset integrity evidence hash")
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError as exc:
            raise RuntimeError("dataset integrity inventory escapes its root") from exc
        if not resolved.is_file() or resolved.is_symlink():
            raise RuntimeError(f"dataset integrity evidence file is missing: {resolved}")
        if sha256_file(resolved) != expected:
            raise RuntimeError(f"dataset integrity evidence hash mismatch: {resolved}")
        count += 1
    if count != 4:
        raise RuntimeError("dataset integrity inventory must sign exactly four payloads")
    return count


def verify_dataset_integrity(root: Path) -> dict:
    if not (root / "TERMINAL_ACCEPTED").is_file() or (root / "TERMINAL_REJECTED").exists():
        raise RuntimeError("Mem-Gallery dataset integrity is not terminal accepted")
    required = (
        "dataset-integrity.json",
        "question-index.jsonl",
        "QID_ORDER.txt",
        "image-references.json",
    )
    for name in required:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"missing non-symlink dataset integrity payload: {name}")
    signed = verify_inventory(root)
    payload = load_json(root / "dataset-integrity.json")
    if payload.get("status") != "TERMINAL_ACCEPTED":
        raise RuntimeError("dataset-integrity.json is not terminal accepted")
    identity = payload.get("stable_identity", {})
    for key, expected in EXPECTED_INTEGRITY.items():
        if identity.get(key) != expected:
            raise RuntimeError(f"Mem-Gallery stable identity mismatch: {key}")
    if sha256_file(root / "QID_ORDER.txt") != identity.get("qid_order_sha256"):
        raise RuntimeError("Mem-Gallery QID order hash mismatch")
    if sha256_file(root / "question-index.jsonl") != identity.get("question_index_sha256"):
        raise RuntimeError("Mem-Gallery question-index hash mismatch")
    return {
        "status": payload["status"],
        "dataset_semantic_identity_sha256": payload["dataset_semantic_identity_sha256"],
        "qid_order_sha256": identity["qid_order_sha256"],
        "question_index_sha256": identity["question_index_sha256"],
        "signed_payloads": signed,
    }


def verify_ownership(ledger_path: Path, remote_root: Path, prefetch_manifest: Path) -> dict:
    ledger = load_json(ledger_path)
    if ledger.get("status") != "FROZEN_BEFORE_SIGLIP2_MATERIALIZATION_AND_ANY_MODEL_CLEANUP":
        raise RuntimeError("ownership ledger v2 is not the frozen successor")
    candidates = [
        row for row in ledger.get("new_project_owned_candidates", [])
        if row.get("repository") == EXPECTED_REPOSITORY
    ]
    if len(candidates) != 1:
        raise RuntimeError("SigLIP2 is absent or duplicated in ownership ledger v2")
    row = candidates[0]
    expected_target = remote_root / EXPECTED_TARGET_SUFFIX
    resolved_target = Path(os.path.expandvars(row["target"].replace(
        "${AGENT_ENHANCE_REMOTE_ROOT}", str(remote_root)
    )))
    if (
        row.get("revision") != EXPECTED_REVISION
        or resolved_target != expected_target
        or row.get("required_dependents") != ["memgallery-m2a", "memgallery-v-mem"]
        or row.get("expected_files") != 9
        or row.get("expected_bytes") != 1540625721
        or row.get("cleanup_eligible") is not False
    ):
        raise RuntimeError("SigLIP2 ownership identity or dependent surface mismatch")
    if sha256_file(prefetch_manifest) != row.get("prefetch_manifest_sha256"):
        raise RuntimeError("ownership ledger and SigLIP2 prefetch manifest differ")
    return {
        "ledger_sha256": sha256_file(ledger_path),
        "model_id": row["model_id"],
        "target": str(expected_target),
        "required_dependents": row["required_dependents"],
        "cleanup_eligible": row["cleanup_eligible"],
    }


def proc_cmdlines(proc_root: Path = Path("/proc")) -> list[str]:
    rows: list[str] = []
    own_pid = os.getpid()
    if not proc_root.is_dir():
        return rows
    for entry in proc_root.iterdir():
        if not entry.name.isdigit() or int(entry.name) == own_pid:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError, IsADirectoryError):
            continue
        text = raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
        if text:
            rows.append(text)
    return rows


def listening_ports(proc_net_root: Path = Path("/proc/net")) -> set[int]:
    ports: set[int] = set()
    for name in ("tcp", "tcp6"):
        path = proc_net_root / name
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[1:]
        except (FileNotFoundError, PermissionError):
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 4 or fields[3] != "0A":
                continue
            try:
                ports.add(int(fields[1].rsplit(":", 1)[1], 16))
            except (IndexError, ValueError):
                raise RuntimeError(f"malformed socket table row in {path}")
    return ports


def assert_resources_released(
    command_lines: Iterable[str], observed_listening_ports: set[int]
) -> None:
    offenders = sorted({
        line for line in command_lines
        if any(token in line for token in BLOCKED_PROCESS_TOKENS)
    })
    if offenders:
        raise RuntimeError(f"Wave-1 or model-service process remains active: {offenders[0]}")
    blocked = sorted(BLOCKED_PORTS.intersection(observed_listening_ports))
    if blocked:
        raise RuntimeError(f"blocked model-service ports remain listening: {blocked}")


def preflight(
    *,
    contract_path: Path,
    ledger_path: Path,
    prefetch_manifest: Path,
    materializer: Path,
    remote_root: Path,
    wave1_controller_root: Path,
    dataset_integrity_root: Path,
    command_lines: Iterable[str] | None = None,
    observed_listening_ports: set[int] | None = None,
) -> dict:
    remote_root = validate_remote_root(remote_root)
    contract = load_json(contract_path)
    if contract.get("status") != "FROZEN_AWAITING_WAVE1_DATA_AND_OWNERSHIP_GATES":
        raise RuntimeError("SigLIP2 materialization contract is not frozen behind all gates")
    manifest_ref = contract["prefetch_manifest"]
    if prefetch_manifest.name != Path(manifest_ref["path"]).name:
        raise RuntimeError("unexpected SigLIP2 prefetch manifest path")
    if sha256_file(prefetch_manifest) != manifest_ref["sha256"]:
        raise RuntimeError("SigLIP2 prefetch manifest hash mismatch")
    if sha256_file(materializer) != contract["implementation"]["downloader_sha256"]:
        raise RuntimeError("SigLIP2 materializer hash mismatch")
    model = contract["model"]
    expected_target = remote_root / EXPECTED_TARGET_SUFFIX
    expected_evidence = remote_root / "runs/memgallery-siglip2-model-materialization-20260904-v1"
    if (
        model.get("repository") != EXPECTED_REPOSITORY
        or model.get("revision") != EXPECTED_REVISION
        or Path(model.get("target", "")) != expected_target
        or Path(model.get("evidence_root", "")) != expected_evidence
    ):
        raise RuntimeError("SigLIP2 materialization contract path or identity drift")
    if not (wave1_controller_root / "TERMINAL_ACCEPTED").is_file():
        raise RuntimeError("Wave 1 controller is not terminal accepted")
    if (wave1_controller_root / "TERMINAL_REJECTED").exists():
        raise RuntimeError("Wave 1 controller has a terminal rejection marker")

    resources = list(command_lines) if command_lines is not None else proc_cmdlines()
    ports = observed_listening_ports if observed_listening_ports is not None else listening_ports()
    assert_resources_released(resources, ports)
    integrity = verify_dataset_integrity(dataset_integrity_root)
    ownership = verify_ownership(ledger_path, remote_root, prefetch_manifest)
    if expected_target.exists() or expected_evidence.exists():
        raise RuntimeError("SigLIP2 target or evidence root already exists")
    return {
        "schema_version": "agentenhance.memgallery_siglip2_materialization_preflight.v1",
        "status": "PREFLIGHT_ACCEPTED",
        "contract_sha256": sha256_file(contract_path),
        "prefetch_manifest_sha256": sha256_file(prefetch_manifest),
        "materializer_sha256": sha256_file(materializer),
        "wave1_controller_root": str(wave1_controller_root),
        "dataset_integrity": integrity,
        "ownership": ownership,
        "blocked_processes": 0,
        "blocked_listening_ports": [],
        "target_absent": True,
        "evidence_root_absent": True,
        "network_requests_started": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--ownership-ledger", type=Path, required=True)
    parser.add_argument("--prefetch-manifest", type=Path, required=True)
    parser.add_argument("--materializer", type=Path, required=True)
    parser.add_argument("--remote-root", type=Path, required=True)
    parser.add_argument("--wave1-controller-root", type=Path, required=True)
    parser.add_argument("--dataset-integrity-root", type=Path, required=True)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        report = preflight(
            contract_path=args.contract.resolve(),
            ledger_path=args.ownership_ledger.resolve(),
            prefetch_manifest=args.prefetch_manifest.resolve(),
            materializer=args.materializer.resolve(),
            remote_root=args.remote_root.resolve(),
            wave1_controller_root=args.wave1_controller_root.resolve(),
            dataset_integrity_root=args.dataset_integrity_root.resolve(),
        )
    except Exception as exc:
        print(json.dumps({
            "schema_version": "agentenhance.memgallery_siglip2_materialization_preflight.v1",
            "status": "PREFLIGHT_REJECTED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "network_requests_started": 0,
            "mutation_performed": False,
        }, sort_keys=True), file=sys.stderr)
        return 4
    print(json.dumps(report, sort_keys=True))
    if not args.execute:
        return 0
    if args.python is None or not args.python.is_absolute():
        raise SystemExit("--execute requires an absolute --python interpreter")
    if not args.python.is_file() or args.python.is_symlink():
        raise SystemExit("--python must be an existing non-symlink interpreter")
    evidence_root = args.remote_root.resolve() / "runs/memgallery-siglip2-model-materialization-20260904-v1"
    command = [
        str(args.python), str(args.materializer.resolve()),
        "--prefetch-manifest", str(args.prefetch_manifest.resolve()),
        "--repository", EXPECTED_REPOSITORY,
        "--evidence-root", str(evidence_root),
        "--timeout-seconds", "600",
    ]
    environment = os.environ.copy()
    environment["AGENT_ENHANCE_REMOTE_ROOT"] = str(args.remote_root.resolve())
    completed = subprocess.run(command, check=False, env=environment)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
