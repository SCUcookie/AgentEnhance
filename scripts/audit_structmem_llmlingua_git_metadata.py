#!/usr/bin/env python3
"""Audit frozen LLMLingua Git metadata without materializing model weights."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY = "https://huggingface.co/microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank"
REVISION = "5f0c82792b7ea14c6484e015b6a072009496b7f2"
TARGET_RELATIVE = Path("third_party/wma-r1-wave5-model-metadata-20260904-v1/llmlingua")
EVIDENCE_RELATIVE = Path("runs/wma-r1-wave5-structmem-llmlingua-metadata-20260904-v1")
MAX_GIT_BYTES = 64 * 1024 * 1024
LFS_PATTERN = re.compile(
    rb"\Aversion https://git-lfs\.github\.com/spec/v1\noid sha256:([0-9a-f]{64})\nsize ([0-9]+)\n?\Z"
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_project_root(path: Path) -> Path:
    path = path.resolve()
    if not path.is_absolute() or path.is_symlink() or path.name != "AgentEnhance":
        raise ValueError("project root must be an absolute non-symlink AgentEnhance directory")
    if not str(path).startswith(("/data1/", "/data2/")):
        raise ValueError("project root must be under /data1 or /data2")
    return path


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ)
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=1800,
    )


def parse_lfs_pointer(payload: bytes) -> dict[str, object] | None:
    match = LFS_PATTERN.fullmatch(payload)
    if match is None:
        return None
    return {"sha256": match.group(1).decode(), "bytes": int(match.group(2))}


def tree_rows(target: Path) -> list[dict[str, object]]:
    raw = run(["git", "ls-tree", "-r", "-z", "--long", REVISION], cwd=target).stdout
    rows = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        metadata, raw_path = item.split(b"\t", 1)
        mode, kind, object_id, git_size = metadata.decode().split()
        if mode == "160000" or kind != "blob":
            raise RuntimeError(f"unsupported Git tree entry: {metadata!r}")
        payload = run(["git", "cat-file", "blob", object_id], cwd=target).stdout
        pointer = parse_lfs_pointer(payload)
        rows.append(
            {
                "path": raw_path.decode("utf-8"),
                "git_blob": object_id,
                "git_blob_bytes": int(git_size),
                "git_blob_sha256": sha256_bytes(payload),
                "lfs": pointer,
            }
        )
    return sorted(rows, key=lambda row: str(row["path"]))


def directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def write_evidence_inventory(root: Path) -> None:
    lines = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.is_file() and path.name not in {"EVIDENCE_SHA256SUMS", "TERMINAL_ACCEPTED", "TERMINAL_REJECTED"}:
            lines.append(f"{sha256_file(path)}  {path}\n")
    (root / "EVIDENCE_SHA256SUMS").write_text("".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    root = validate_project_root(args.project_root)
    target = root / TARGET_RELATIVE
    evidence = root / EVIDENCE_RELATIVE
    if target.exists() or evidence.exists():
        raise SystemExit("refusing existing metadata target or evidence root")
    evidence.mkdir(parents=True)
    started_at = now()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        clone = run(["git", "clone", "--no-checkout", REPOSITORY, str(target)])
        (evidence / "git-clone.stdout").write_bytes(clone.stdout)
        (evidence / "git-clone.stderr").write_bytes(clone.stderr)
        origin = run(["git", "config", "--get", "remote.origin.url"], cwd=target).stdout.decode().strip()
        run(["git", "cat-file", "-e", f"{REVISION}^{{commit}}"], cwd=target)
        if origin.rstrip("/") != REPOSITORY.rstrip("/"):
            raise RuntimeError(f"origin mismatch: {origin}")
        rows = tree_rows(target)
        by_path = {str(row["path"]): row for row in rows}
        model = by_path.get("model.safetensors")
        if model is None or model["lfs"] is None:
            raise RuntimeError("model.safetensors is not represented by a valid LFS pointer")
        pointer_rows = [row for row in rows if row["lfs"] is not None]
        git_bytes = directory_bytes(target)
        if git_bytes > MAX_GIT_BYTES:
            raise RuntimeError(f"metadata clone exceeds byte ceiling: {git_bytes}")
        if any((target / str(row["path"])).exists() for row in pointer_rows):
            raise RuntimeError("an LFS payload appeared in the unmaterialized worktree")
        result = {
            "schema_version": "agentenhance.structmem_llmlingua_git_metadata.v1",
            "status": "TERMINAL_ACCEPTED",
            "repository": REPOSITORY,
            "revision": REVISION,
            "target": str(target),
            "started_at": started_at,
            "finished_at": now(),
            "tree_file_count": len(rows),
            "lfs_pointer_count": len(pointer_rows),
            "git_metadata_bytes": git_bytes,
            "files": rows,
            "model_payload_materialized": False,
            "scientific_result_eligible": False,
        }
        record = evidence / "model-metadata.json"
        record.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        write_evidence_inventory(evidence)
        (evidence / "TERMINAL_ACCEPTED").touch()
        print(json.dumps({"status": result["status"], "tree_file_count": len(rows), "lfs_pointer_count": len(pointer_rows), "model": model}, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.structmem_llmlingua_git_metadata_failure.v1",
            "status": "TERMINAL_REJECTED",
            "repository": REPOSITORY,
            "revision": REVISION,
            "target": str(target),
            "started_at": started_at,
            "finished_at": now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "partial_target_retained": target.exists(),
        }
        (evidence / "model-metadata-failure.json").write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        write_evidence_inventory(evidence)
        (evidence / "TERMINAL_REJECTED").touch()
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
