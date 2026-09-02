#!/usr/bin/env python3
"""Materialize an exact ModelScope Git commit and its LFS objects read-only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def output(command: list[str], *, cwd: Path) -> str:
    return subprocess.check_output(command, cwd=cwd, text=True).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--incoming-root", type=Path, required=True)
    parser.add_argument("--final-dir", type=Path, required=True)
    parser.add_argument("--concurrent-transfers", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.final_dir.exists():
        raise FileExistsError(f"refusing to overwrite final model directory: {args.final_dir}")
    if not args.source_url.startswith("https://www.modelscope.cn/"):
        raise ValueError("source URL must be an official ModelScope HTTPS repository")
    if len(args.revision) != 40 or any(char not in "0123456789abcdef" for char in args.revision):
        raise ValueError("revision must be a lowercase 40-character Git commit")

    args.incoming_root.mkdir(parents=True, exist_ok=True)
    partial = args.incoming_root / f"{args.final_dir.name}.git-lfs-partial.{args.revision[:12]}"
    git_dir = partial / ".git"
    source_record = partial / ".agent-enhance-source-commit"
    git_env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1")

    if not git_dir.is_dir():
        if partial.exists():
            if any(partial.iterdir()):
                raise RuntimeError(f"non-resumable partial directory exists: {partial}")
            partial.rmdir()
        run(["git", "clone", "--no-checkout", args.source_url, str(partial)], env=git_env)

    run(["git", "fetch", "origin", args.revision], cwd=partial, env=git_env)
    run(["git", "checkout", "--detach", args.revision], cwd=partial, env=git_env)
    resolved_revision = output(["git", "rev-parse", "HEAD"], cwd=partial)
    if resolved_revision != args.revision:
        raise RuntimeError(f"resolved revision mismatch: {resolved_revision}")

    run(
        [
            "git",
            "-c",
            f"lfs.concurrenttransfers={args.concurrent_transfers}",
            "lfs",
            "pull",
            "origin",
            args.revision,
        ],
        cwd=partial,
    )
    run(["git", "lfs", "fsck"], cwd=partial)
    lfs_names = [
        line
        for line in output(["git", "lfs", "ls-files", "--name-only"], cwd=partial).splitlines()
        if line
    ]
    if not lfs_names:
        raise RuntimeError("repository declares no Git LFS files")
    for name in lfs_names:
        path = partial / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"missing or unsafe LFS working-tree file: {name}")
        with path.open("rb") as handle:
            if handle.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX:
                raise RuntimeError(f"unresolved Git LFS pointer: {name}")

    links = [
        path
        for path in partial.rglob("*")
        if ".git" not in path.relative_to(partial).parts and path.is_symlink()
    ]
    if links:
        raise RuntimeError(f"snapshot contains symlinks: {links[:3]}")

    source_record.write_text(args.revision + "\n", encoding="utf-8")
    excluded = {"MODEL_FILES_SHA256SUMS", "placement-manifest.json"}
    files = [
        path
        for path in sorted(partial.rglob("*"))
        if path.is_file()
        and ".git" not in path.relative_to(partial).parts
        and path.name not in excluded
    ]
    records = [
        {
            "path": path.relative_to(partial).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in files
    ]
    inventory = partial / "MODEL_FILES_SHA256SUMS"
    inventory.write_text(
        "".join(f"{record['sha256']}  {record['path']}\n" for record in records),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "model_placement_manifest.v1",
        "model_id": args.model_id,
        "source": "modelscope_git_lfs",
        "source_url": args.source_url,
        "revision": args.revision,
        "materialized_at_utc": datetime.now(timezone.utc).isoformat(),
        "file_count": len(records),
        "lfs_file_count": len(lfs_names),
        "total_bytes": sum(record["bytes"] for record in records),
        "model_files_inventory_sha256": sha256(inventory),
        "read_only_after_publish": True,
    }
    (partial / "placement-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    shutil.rmtree(git_dir)
    args.final_dir.parent.mkdir(parents=True, exist_ok=True)
    os.replace(partial, args.final_dir)
    for path in sorted(args.final_dir.rglob("*"), reverse=True):
        mode = path.stat().st_mode
        path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    mode = args.final_dir.stat().st_mode
    args.final_dir.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
