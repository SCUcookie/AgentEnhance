#!/usr/bin/env python3
"""Materialize an exact Hugging Face dataset snapshot after project-resource gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO


BLOCK_BYTES = 8 * 1024 * 1024
PROJECT_PORTS = (18113, 18114, 18120, 18220, 18221, 18222)
ALLOWED_DATASET_SCOPES = (
    Path("/data1/2026/ldh/AgentEnhance/datasets/raw"),
    Path("/data2/2026/ldh/AgentEnhance/datasets/raw"),
)
ALLOWED_RUN_SCOPES = (
    Path("/data1/2026/ldh/AgentEnhance/runs"),
    Path("/data2/2026/ldh/AgentEnhance/runs"),
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_relative_file(raw: str) -> PurePosixPath:
    path = PurePosixPath(raw)
    if (
        not raw
        or path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or any(not part for part in path.parts)
        or raw.endswith("/")
    ):
        raise ValueError(f"unsafe dataset file path: {raw}")
    return path


def validate_exact_child(path: Path, scopes: tuple[Path, ...], label: str) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{label} must be absolute and not a symlink: {path}")
    if not any(path.parent == scope and path.name for scope in scopes):
        raise ValueError(f"{label} must be an exact child of an allowed scope: {path}")


def validate_under_scope(path: Path, scopes: tuple[Path, ...], label: str) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{label} must be absolute and not a symlink: {path}")
    if not any(path == scope or scope in path.parents for scope in scopes):
        raise ValueError(f"{label} is outside allowed scopes: {path}")


def validate_manifest(payload: dict) -> list[dict]:
    if payload.get("status") != "FROZEN_BEFORE_DOWNLOAD":
        raise ValueError("dataset manifest is not frozen before download")
    source = payload.get("source", {})
    repository = source.get("repository")
    revision = source.get("revision")
    if not isinstance(repository, str) or repository.count("/") != 1:
        raise ValueError("invalid dataset repository")
    if not isinstance(revision, str) or len(revision) != 40 or any(
        char not in "0123456789abcdef" for char in revision
    ):
        raise ValueError("dataset revision must be an immutable Git commit")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("dataset manifest has no files")
    paths = [str(item.get("path", "")) for item in files]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ValueError("dataset paths must be unique and sorted")
    for item in files:
        validate_relative_file(str(item["path"]))
        size = item.get("bytes")
        git_oid = item.get("git_oid")
        if not isinstance(size, int) or size < 0:
            raise ValueError(f"invalid byte size for {item['path']}")
        if (
            not isinstance(git_oid, str)
            or len(git_oid) != 40
            or any(char not in "0123456789abcdef" for char in git_oid)
        ):
            raise ValueError(f"invalid Git oid for {item['path']}")
        lfs_sha256 = item.get("lfs_sha256")
        if lfs_sha256 is not None and (
            not isinstance(lfs_sha256, str)
            or len(lfs_sha256) != 64
            or any(char not in "0123456789abcdef" for char in lfs_sha256)
        ):
            raise ValueError(f"invalid LFS SHA-256 for {item['path']}")
    expected = payload.get("expected", {})
    if len(files) != expected.get("files") or sum(item["bytes"] for item in files) != expected.get(
        "bytes"
    ):
        raise ValueError("dataset manifest aggregate mismatch")
    return files


def dataset_file_url(repository: str, revision: str, relative_path: str) -> str:
    repo = "/".join(urllib.parse.quote(part, safe="") for part in repository.split("/"))
    encoded_revision = urllib.parse.quote(revision, safe="")
    encoded_path = "/".join(
        urllib.parse.quote(part, safe="") for part in validate_relative_file(relative_path).parts
    )
    return (
        f"https://huggingface.co/datasets/{repo}/resolve/"
        f"{encoded_revision}/{encoded_path}?download=true"
    )


def stream_exact_file(
    source: BinaryIO, destination: Path, expected_bytes: int
) -> tuple[int, str, str]:
    observed_bytes = 0
    sha256 = hashlib.sha256()
    git_blob_sha1 = hashlib.sha1()
    git_blob_sha1.update(f"blob {expected_bytes}\0".encode("ascii"))
    with destination.open("xb") as handle:
        while True:
            block = source.read(BLOCK_BYTES)
            if not block:
                break
            observed_bytes += len(block)
            if observed_bytes > expected_bytes:
                raise RuntimeError(f"download exceeded frozen byte size: {destination}")
            sha256.update(block)
            git_blob_sha1.update(block)
            handle.write(block)
        handle.flush()
        os.fsync(handle.fileno())
    return observed_bytes, sha256.hexdigest(), git_blob_sha1.hexdigest()


def active_tmux_sessions(prefix: str) -> list[str]:
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"tmux inventory failed with exit code {result.returncode}")
    return sorted(name for name in result.stdout.splitlines() if name.startswith(prefix))


def listening_project_ports(ports: tuple[int, ...] = PROJECT_PORTS) -> list[int]:
    listening: list[int] = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            candidate.settimeout(0.2)
            if candidate.connect_ex(("127.0.0.1", port)) == 0:
                listening.append(port)
    return listening


def observed_files(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def append_jsonl(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def atomic_json(path: Path, payload: dict) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--stage-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--required-marker", type=Path, required=True)
    parser.add_argument("--forbidden-marker", type=Path, required=True)
    parser.add_argument("--tmux-prefix", default="agentenhance-wma")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--minimum-free-margin-bytes", type=int, default=1073741824)
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    target = args.target.resolve()
    stage_root = args.stage_root.resolve()
    evidence_root = args.evidence_root.resolve()
    required_marker = args.required_marker.resolve()
    forbidden_marker = args.forbidden_marker.resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = validate_manifest(payload)
    validate_exact_child(target, ALLOWED_DATASET_SCOPES, "target")
    validate_exact_child(stage_root, ALLOWED_DATASET_SCOPES, "stage root")
    validate_exact_child(evidence_root, ALLOWED_RUN_SCOPES, "evidence root")
    validate_under_scope(required_marker, ALLOWED_RUN_SCOPES, "required marker")
    validate_under_scope(forbidden_marker, ALLOWED_RUN_SCOPES, "forbidden marker")
    if stage_root.parent != target.parent or not stage_root.name.startswith(target.name + ".partial-"):
        raise SystemExit("stage root must be a named partial sibling of the exact target")
    if args.timeout_seconds <= 0 or args.minimum_free_margin_bytes < 0:
        raise SystemExit("invalid timeout or free-space margin")
    if target.exists() or stage_root.exists() or evidence_root.exists():
        raise SystemExit("refusing an existing target, stage root, or evidence root")
    if not required_marker.is_file() or forbidden_marker.exists():
        raise SystemExit(
            f"prerequisite marker gate failed: required={required_marker}, forbidden={forbidden_marker}"
        )
    tmux_sessions = active_tmux_sessions(args.tmux_prefix)
    active_ports = listening_project_ports()
    if tmux_sessions or active_ports:
        raise SystemExit(
            f"project resources are active: tmux={tmux_sessions}, ports={active_ports}"
        )
    expected_bytes = int(payload["expected"]["bytes"])
    free_bytes = shutil.disk_usage(target.parent).free
    if free_bytes < expected_bytes + args.minimum_free_margin_bytes:
        raise SystemExit("insufficient free space for frozen dataset plus safety margin")

    evidence_root.mkdir(parents=False)
    stage_root.mkdir(parents=False)
    started_at = now()
    progress_path = evidence_root / "download-progress.jsonl"
    inventory: list[dict] = []
    current: dict | None = None
    try:
        source = payload["source"]
        for index, row in enumerate(files, start=1):
            relative = str(row["path"])
            final = stage_root.joinpath(*validate_relative_file(relative).parts)
            final.parent.mkdir(parents=True, exist_ok=True)
            partial = final.with_name(final.name + ".partial")
            requested_url = dataset_file_url(source["repository"], source["revision"], relative)
            current = {
                "index": index,
                "path": relative,
                "logical_request_attempt": 1,
                "retry_count": 0,
                "expected_bytes": row["bytes"],
            }
            request = urllib.request.Request(
                requested_url, headers={"User-Agent": "AgentEnhance-dataset-materializer/1"}
            )
            with urllib.request.urlopen(request, timeout=args.timeout_seconds) as response:
                final_url = urllib.parse.urlparse(response.geturl())
                current.update(
                    {
                        "http_status": response.status,
                        "redirected": response.geturl() != requested_url,
                        "final_scheme": final_url.scheme,
                        "final_hostname": final_url.hostname,
                    }
                )
                if response.status != 200 or final_url.scheme != "https":
                    raise RuntimeError(f"unexpected HTTP response for {relative}")
                observed_bytes, observed_sha256, observed_git_blob_sha1 = stream_exact_file(
                    response, partial, int(row["bytes"])
                )
            current.update(
                {
                    "observed_bytes": observed_bytes,
                    "observed_sha256": observed_sha256,
                    "observed_git_blob_sha1": observed_git_blob_sha1,
                }
            )
            if observed_bytes != row["bytes"]:
                raise RuntimeError(f"byte size mismatch for {relative}")
            if "lfs_sha256" in row:
                if observed_sha256 != row["lfs_sha256"]:
                    raise RuntimeError(f"LFS SHA-256 mismatch for {relative}")
                frozen_identity_type = "lfs-sha256"
            else:
                if observed_git_blob_sha1 != row["git_oid"]:
                    raise RuntimeError(f"Git blob SHA-1 mismatch for {relative}")
                frozen_identity_type = "git-blob-sha1"
            partial.replace(final)
            inventory_row = {
                "path": relative,
                "bytes": observed_bytes,
                "sha256": observed_sha256,
                "git_blob_sha1": observed_git_blob_sha1,
                "frozen_identity_type": frozen_identity_type,
            }
            inventory.append(inventory_row)
            append_jsonl(progress_path, current)
            current = None

        expected_paths = [str(row["path"]) for row in files]
        if observed_files(stage_root) != expected_paths:
            raise RuntimeError("materialized dataset paths differ from frozen manifest")
        if sum(row["bytes"] for row in inventory) != expected_bytes:
            raise RuntimeError("materialized dataset total bytes differ from frozen manifest")
        stage_root.replace(target)
        result = {
            "schema_version": "agentenhance.hf_dataset_materialization.v1",
            "status": "TERMINAL_ACCEPTED",
            "repository": source["repository"],
            "revision": source["revision"],
            "target": str(target),
            "stage_root": str(stage_root),
            "source_manifest": str(manifest_path),
            "source_manifest_sha256": sha256_file(manifest_path),
            "started_at": started_at,
            "finished_at": now(),
            "network_retry_count": 0,
            "logical_requests_per_file": 1,
            "file_count": len(inventory),
            "total_bytes": sum(row["bytes"] for row in inventory),
            "free_bytes_before": free_bytes,
            "tmux_sessions_before": tmux_sessions,
            "listening_project_ports_before": active_ports,
            "required_marker": str(required_marker),
            "forbidden_marker_absent": not forbidden_marker.exists(),
            "files": inventory,
        }
        result_path = evidence_root / "dataset-materialization.json"
        atomic_json(result_path, result)
        sums_path = evidence_root / "DATA_SHA256SUMS"
        sums_path.write_text(
            "".join(f"{row['sha256']}  {target / row['path']}\n" for row in inventory),
            encoding="utf-8",
        )
        (evidence_root / "EVIDENCE_SHA256SUMS").write_text(
            f"{sha256_file(result_path)}  {result_path}\n"
            f"{sha256_file(progress_path)}  {progress_path}\n"
            f"{sha256_file(sums_path)}  {sums_path}\n",
            encoding="utf-8",
        )
        (evidence_root / "TERMINAL_ACCEPTED").touch()
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "repository": result["repository"],
                    "revision": result["revision"],
                    "file_count": result["file_count"],
                    "total_bytes": result["total_bytes"],
                    "network_retry_count": result["network_retry_count"],
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.hf_dataset_materialization_failure.v1",
            "status": "TERMINAL_REJECTED",
            "repository": payload["source"]["repository"],
            "revision": payload["source"]["revision"],
            "target": str(target),
            "stage_root": str(stage_root),
            "source_manifest": str(manifest_path),
            "source_manifest_sha256": sha256_file(manifest_path),
            "started_at": started_at,
            "finished_at": now(),
            "network_retry_count": 0,
            "completed_files": len(inventory),
            "completed_bytes": sum(row["bytes"] for row in inventory),
            "current_attempt": current,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "partial_stage_retained": stage_root.exists(),
            "cleanup_authorized": False,
            "required_marker": str(required_marker),
            "forbidden_marker_absent": not forbidden_marker.exists(),
        }
        failure_path = evidence_root / "dataset-materialization-failure.json"
        atomic_json(failure_path, failure)
        evidence_lines = [f"{sha256_file(failure_path)}  {failure_path}\n"]
        if progress_path.exists():
            evidence_lines.append(f"{sha256_file(progress_path)}  {progress_path}\n")
        (evidence_root / "EVIDENCE_SHA256SUMS").write_text("".join(evidence_lines), encoding="utf-8")
        (evidence_root / "TERMINAL_REJECTED").touch()
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
