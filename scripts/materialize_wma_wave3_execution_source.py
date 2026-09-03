#!/usr/bin/env python3
"""Create immutable source-only execution copies for Wave-3 adapters."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


EXPECTED_REVISIONS = {
    "memoryos": "587ed7755c7aed179965792830ff1b5ad9a6fa92",
    "memgas": "c2d4e9fdc331074802a711baf4371197f9194399",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_path(path: Path, leaf: tuple[str, ...]) -> Path:
    path = path.resolve()
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"path must be absolute and not a symlink: {path}")
    parts = path.parts
    if not any(parts[index : index + len(leaf)] == leaf for index in range(len(parts) - len(leaf) + 1)):
        raise ValueError(f"path is outside required scope {leaf}: {path}")
    return path


def git_output(source: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(source), *args], text=True
    ).strip()


def tracked_files(source: Path) -> list[Path]:
    raw = subprocess.check_output(
        ["git", "-C", str(source), "ls-files", "-z"]
    )
    return [Path(item.decode("utf-8")) for item in raw.split(b"\0") if item]


def copy_source(source: Path, destination: Path, method: str) -> list[dict[str, object]]:
    if method == "memoryos":
        prefix = Path("memoryos-pypi")
        output_root = destination / "memoryos_pkg"
    elif method == "memgas":
        prefix = Path(".")
        output_root = destination / "memgas_source"
    else:
        raise ValueError(f"unsupported method: {method}")
    output_root.mkdir(parents=True)
    rows = []
    for tracked in tracked_files(source):
        if method == "memoryos" and prefix not in tracked.parents:
            continue
        relative = tracked.relative_to(prefix) if method == "memoryos" else tracked
        if "__pycache__" in relative.parts or relative.suffix == ".pyc":
            continue
        path = source / tracked
        if not path.is_file():
            raise RuntimeError(f"tracked source is not a regular file: {tracked}")
        target = output_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        rows.append(
            {
                "path": target.relative_to(output_root).as_posix(),
                "bytes": target.stat().st_size,
                "sha256": sha256_file(target),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=("memoryos", "memgas"), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    source = validate_path(args.source, ("AgentEnhance", "third_party"))
    destination = validate_path(args.destination, ("AgentEnhance", "third_party"))
    evidence_root = validate_path(args.evidence_root, ("AgentEnhance", "runs"))
    if destination.exists() or evidence_root.exists():
        raise SystemExit("refusing existing execution source or evidence root")
    evidence_root.mkdir(parents=True)
    started_at = now()
    try:
        revision = git_output(source, "rev-parse", "HEAD")
        if revision != EXPECTED_REVISIONS[args.method]:
            raise RuntimeError(
                f"source revision mismatch: expected {EXPECTED_REVISIONS[args.method]}, got {revision}"
            )
        if git_output(source, "status", "--porcelain"):
            raise RuntimeError("source checkout is dirty")
        files = copy_source(source, destination, args.method)
        if not files or any(row["path"].endswith(".pyc") for row in files):
            raise RuntimeError("invalid source-only execution copy")
        result = {
            "schema_version": "agentenhance.wma_wave3_execution_source.v1",
            "status": "TERMINAL_ACCEPTED",
            "method_id": args.method,
            "source_revision": revision,
            "source": str(source),
            "destination": str(destination),
            "started_at": started_at,
            "finished_at": now(),
            "file_count": len(files),
            "total_bytes": sum(int(row["bytes"]) for row in files),
            "files": files,
        }
        record = evidence_root / "execution-source.json"
        record.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        sums = evidence_root / "EVIDENCE_SHA256SUMS"
        sums.write_text(f"{sha256_file(record)}  {record}\n", encoding="utf-8")
        (evidence_root / "TERMINAL_ACCEPTED").touch()
        print(json.dumps({key: result[key] for key in ("status", "method_id", "file_count", "total_bytes")}, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.wma_wave3_execution_source_failure.v1",
            "status": "TERMINAL_REJECTED",
            "method_id": args.method,
            "source": str(source),
            "destination": str(destination),
            "started_at": started_at,
            "finished_at": now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "partial_destination_retained": destination.exists(),
        }
        record = evidence_root / "execution-source-failure.json"
        record.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (evidence_root / "EVIDENCE_SHA256SUMS").write_text(
            f"{sha256_file(record)}  {record}\n", encoding="utf-8"
        )
        (evidence_root / "TERMINAL_REJECTED").touch()
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
