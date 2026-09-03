#!/usr/bin/env python3
"""Materialize the frozen Hindsight source revision with fail-closed evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY = "https://github.com/vectorize-io/hindsight.git"
REVISION = "5e71494702bc050b6d58e783e6761f6c6cf3b74b"
SOURCE_RELATIVE = Path("third_party/wma-r1-wave4-source-20260904-v1/hindsight")
EVIDENCE_RELATIVE = Path("runs/wma-r1-wave4-hindsight-source-materialization-20260904-v1")
MAX_WORKTREE_BYTES = 768 * 1024 * 1024
PROHIBITED_SUFFIXES = {
    ".bin",
    ".ckpt",
    ".gguf",
    ".onnx",
    ".pt",
    ".pth",
    ".safetensors",
}
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=1800,
    )


def validate_project_root(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_absolute() or resolved.is_symlink():
        raise ValueError("project root must be an absolute non-symlink path")
    if resolved.name != "AgentEnhance":
        raise ValueError("project root must end in AgentEnhance")
    if not str(resolved).startswith(("/data1/", "/data2/")):
        raise ValueError("project root must be under /data1 or /data2")
    return resolved


def tracked_files(target: Path) -> list[Path]:
    result = run(["git", "ls-files", "-z"], cwd=target)
    rows = [Path(item) for item in result.stdout.split("\0") if item]
    if not rows:
        raise RuntimeError("source checkout contains no tracked files")
    return sorted(rows, key=lambda item: item.as_posix())


def write_evidence_inventory(evidence_root: Path) -> None:
    rows = []
    for path in sorted(evidence_root.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.name in {
            "EVIDENCE_SHA256SUMS",
            "TERMINAL_ACCEPTED",
            "TERMINAL_REJECTED",
        }:
            continue
        rows.append(f"{sha256_file(path)}  {path}\n")
    (evidence_root / "EVIDENCE_SHA256SUMS").write_text(
        "".join(rows), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()

    project_root = validate_project_root(args.project_root)
    target = project_root / SOURCE_RELATIVE
    evidence_root = project_root / EVIDENCE_RELATIVE
    if evidence_root.exists():
        raise SystemExit(f"refusing existing evidence root: {evidence_root}")
    evidence_root.mkdir(parents=True)
    started_at = now()
    git_environment = dict(os.environ)
    git_environment["GIT_LFS_SKIP_SMUDGE"] = "1"
    git_environment["GIT_TERMINAL_PROMPT"] = "0"

    try:
        if target.exists():
            raise RuntimeError(f"refusing existing source target: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        clone = run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                REPOSITORY,
                str(target),
            ],
            env=git_environment,
        )
        (evidence_root / "git-clone.stdout").write_text(
            clone.stdout, encoding="utf-8"
        )
        (evidence_root / "git-clone.stderr").write_text(
            clone.stderr, encoding="utf-8"
        )
        checkout = run(
            ["git", "checkout", "--detach", REVISION],
            cwd=target,
            env=git_environment,
        )
        (evidence_root / "git-checkout.stdout").write_text(
            checkout.stdout, encoding="utf-8"
        )
        (evidence_root / "git-checkout.stderr").write_text(
            checkout.stderr, encoding="utf-8"
        )

        head = run(["git", "rev-parse", "HEAD"], cwd=target).stdout.strip()
        origin = run(
            ["git", "config", "--get", "remote.origin.url"], cwd=target
        ).stdout.strip()
        status = run(["git", "status", "--porcelain=v1"], cwd=target).stdout
        submodules = run(
            ["git", "submodule", "status", "--recursive"], cwd=target
        ).stdout.strip()
        if head != REVISION:
            raise RuntimeError(f"revision mismatch: expected {REVISION}, got {head}")
        if origin.rstrip("/") != REPOSITORY.rstrip("/"):
            raise RuntimeError(f"origin mismatch: expected {REPOSITORY}, got {origin}")
        if status:
            raise RuntimeError("source checkout is dirty immediately after checkout")
        if submodules:
            raise RuntimeError("unexpected submodule dependency")

        files = tracked_files(target)
        prohibited = [
            item.as_posix()
            for item in files
            if item.suffix.lower() in PROHIBITED_SUFFIXES
        ]
        lfs_pointers = []
        inventory = []
        total_bytes = 0
        license_candidates = []
        for relative in files:
            path = target / relative
            if not path.is_file() or path.is_symlink():
                raise RuntimeError(f"tracked path is not a regular file: {relative}")
            size = path.stat().st_size
            total_bytes += size
            if size <= 4096 and path.read_bytes().startswith(LFS_POINTER_PREFIX):
                lfs_pointers.append(relative.as_posix())
            if relative.name.lower().startswith("license"):
                license_candidates.append(relative.as_posix())
            inventory.append(
                {
                    "path": relative.as_posix(),
                    "bytes": size,
                    "sha256": sha256_file(path),
                }
            )
        if prohibited:
            raise RuntimeError(
                f"prohibited model-like files in source checkout: {prohibited[:20]}"
            )
        if lfs_pointers:
            raise RuntimeError(f"unmaterialized Git LFS pointers: {lfs_pointers[:20]}")
        if total_bytes > MAX_WORKTREE_BYTES:
            raise RuntimeError(
                f"source worktree exceeds byte ceiling: {total_bytes} > {MAX_WORKTREE_BYTES}"
            )
        if not license_candidates:
            raise RuntimeError("source checkout contains no tracked license file")
        license_text = "\n".join(
            (target / relative).read_text(encoding="utf-8", errors="replace")
            for relative in license_candidates
        ).lower()
        if "mit license" not in license_text:
            raise RuntimeError("tracked license files do not identify the MIT License")

        source_sums = evidence_root / "SOURCE_SHA256SUMS"
        source_sums.write_text(
            "".join(f"{row['sha256']}  {target / row['path']}\n" for row in inventory),
            encoding="utf-8",
        )
        result = {
            "schema_version": "agentenhance.git_source_materialization.v1",
            "status": "TERMINAL_ACCEPTED",
            "method_id": "hindsight",
            "repository": REPOSITORY,
            "revision": REVISION,
            "git_tree": run(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=target
            ).stdout.strip(),
            "target": str(target),
            "started_at": started_at,
            "finished_at": now(),
            "tracked_file_count": len(inventory),
            "tracked_total_bytes": total_bytes,
            "worktree_clean": True,
            "submodule_count": 0,
            "git_lfs_pointer_count": 0,
            "prohibited_weight_file_count": 0,
            "license": "MIT",
            "license_files": license_candidates,
            "source_inventory": inventory,
            "scientific_result_eligible": False,
        }
        result_path = evidence_root / "source-materialization.json"
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        write_evidence_inventory(evidence_root)
        (evidence_root / "TERMINAL_ACCEPTED").touch()
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in (
                        "status",
                        "method_id",
                        "revision",
                        "git_tree",
                        "tracked_file_count",
                        "tracked_total_bytes",
                        "license",
                    )
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.git_source_materialization_failure.v1",
            "status": "TERMINAL_REJECTED",
            "method_id": "hindsight",
            "repository": REPOSITORY,
            "revision": REVISION,
            "target": str(target),
            "started_at": started_at,
            "finished_at": now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "partial_target_retained": target.exists(),
            "cleanup_authorized": False,
        }
        (evidence_root / "source-materialization-failure.json").write_text(
            json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        write_evidence_inventory(evidence_root)
        (evidence_root / "TERMINAL_REJECTED").touch()
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
