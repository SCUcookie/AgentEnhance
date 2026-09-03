#!/usr/bin/env python3
"""Create a minimal immutable execution-source copy for Hindsight Wave 4."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


EXPECTED_REVISION = "5e71494702bc050b6d58e783e6761f6c6cf3b74b"
EXPECTED_FILE_COUNT = 563
EXPECTED_TOTAL_BYTES = 9_417_481
INCLUDE_EXACT = {
    Path("LICENSE"),
    Path("pyproject.toml"),
    Path("hindsight-all/README.md"),
    Path("hindsight-all/pyproject.toml"),
    Path("hindsight-api-slim/README.md"),
    Path("hindsight-api-slim/pyproject.toml"),
    Path("hindsight-clients/python/README.md"),
    Path("hindsight-clients/python/pyproject.toml"),
    Path("hindsight-embed/README.md"),
    Path("hindsight-embed/pyproject.toml"),
}
INCLUDE_DIRS = (
    Path("hindsight-all/hindsight"),
    Path("hindsight-api-slim/hindsight_api"),
    Path("hindsight-clients/python/hindsight_client"),
    Path("hindsight-clients/python/hindsight_client_api"),
    Path("hindsight-embed/hindsight_embed"),
)


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
    if not any(
        parts[index : index + len(leaf)] == leaf
        for index in range(len(parts) - len(leaf) + 1)
    ):
        raise ValueError(f"path is outside required scope {leaf}: {path}")
    return path


def git_output(source: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def tracked_files(source: Path) -> list[Path]:
    raw = subprocess.check_output(["git", "-C", str(source), "ls-files", "-z"])
    return [Path(item.decode("utf-8")) for item in raw.split(b"\0") if item]


def selected(relative: Path) -> bool:
    if relative in INCLUDE_EXACT:
        return True
    return any(prefix == relative or prefix in relative.parents for prefix in INCLUDE_DIRS)


def copy_source(source: Path, destination: Path) -> list[dict[str, object]]:
    destination.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    for relative in tracked_files(source):
        if not selected(relative):
            continue
        if "__pycache__" in relative.parts or relative.suffix == ".pyc":
            raise RuntimeError(f"tracked bytecode entered selected source: {relative}")
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"selected source is not a regular file: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        rows.append(
            {
                "path": relative.as_posix(),
                "bytes": target.stat().st_size,
                "sha256": sha256_file(target),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
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
        if revision != EXPECTED_REVISION:
            raise RuntimeError(
                f"source revision mismatch: expected {EXPECTED_REVISION}, got {revision}"
            )
        if git_output(source, "status", "--porcelain"):
            raise RuntimeError("source checkout is dirty")
        files = copy_source(source, destination)
        total_bytes = sum(int(row["bytes"]) for row in files)
        if len(files) != EXPECTED_FILE_COUNT or total_bytes != EXPECTED_TOTAL_BYTES:
            raise RuntimeError(
                "selected source cardinality mismatch: "
                f"expected {EXPECTED_FILE_COUNT}/{EXPECTED_TOTAL_BYTES}, "
                f"got {len(files)}/{total_bytes}"
            )
        result = {
            "schema_version": "agentenhance.wma_wave4_hindsight_execution_source.v1",
            "status": "TERMINAL_ACCEPTED",
            "method_id": "hindsight",
            "source_revision": revision,
            "source": str(source),
            "destination": str(destination),
            "started_at": started_at,
            "finished_at": now(),
            "file_count": len(files),
            "total_bytes": total_bytes,
            "files": files,
        }
        record = evidence_root / "execution-source.json"
        record.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        sums = evidence_root / "EVIDENCE_SHA256SUMS"
        sums.write_text(f"{sha256_file(record)}  {record}\n", encoding="utf-8")
        (evidence_root / "TERMINAL_ACCEPTED").touch()
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in ("status", "method_id", "file_count", "total_bytes")
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.wma_wave4_hindsight_execution_source_failure.v1",
            "status": "TERMINAL_REJECTED",
            "method_id": "hindsight",
            "source": str(source),
            "destination": str(destination),
            "started_at": started_at,
            "finished_at": now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "partial_destination_retained": destination.exists(),
        }
        record = evidence_root / "execution-source-failure.json"
        record.write_text(
            json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (evidence_root / "EVIDENCE_SHA256SUMS").write_text(
            f"{sha256_file(record)}  {record}\n", encoding="utf-8"
        )
        (evidence_root / "TERMINAL_REJECTED").touch()
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
