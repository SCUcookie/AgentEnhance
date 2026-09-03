#!/usr/bin/env python3
"""Materialize the frozen uv binary used for Hindsight dependency export."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


VERSION = "0.12.9"
TARGET_TRIPLE = "x86_64-unknown-linux-gnu"
ARCHIVE_NAME = f"uv-{TARGET_TRIPLE}.tar.gz"
ARCHIVE_URL = f"https://github.com/astral-sh/uv/releases/download/{VERSION}/{ARCHIVE_NAME}"
CHECKSUM_URL = f"{ARCHIVE_URL}.sha256"
ARCHIVE_BYTES = 19_423_276
ARCHIVE_SHA256 = "ec7a99cd05e0cd7f80243f135ce1361c76835cb0ee60055d14d20eba8eba1460"
CHECKSUM_BYTES = 101
CHECKSUM_SHA256 = "18f88ae6a13764973e76d72c1a4ade28c70b53d8279f5b4715e48b2291c264a5"
EXPECTED_MEMBERS = {
    PurePosixPath(f"uv-{TARGET_TRIPLE}"),
    PurePosixPath(f"uv-{TARGET_TRIPLE}/uv"),
    PurePosixPath(f"uv-{TARGET_TRIPLE}/uvx"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
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


def download(url: str, destination: Path) -> None:
    subprocess.run(
        [
            "curl",
            "--fail",
            "--show-error",
            "--location",
            "--retry",
            "0",
            "--connect-timeout",
            "30",
            "--max-time",
            "900",
            "--limit-rate",
            "512K",
            "--output",
            str(destination),
            url,
        ],
        check=True,
    )


def validate_archive_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    paths = {PurePosixPath(member.name) for member in members}
    if paths != EXPECTED_MEMBERS:
        raise RuntimeError(f"unexpected archive members: {sorted(str(path) for path in paths)}")
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"unsafe archive path: {member.name}")
        if not (member.isdir() or member.isfile()):
            raise RuntimeError(f"non-regular archive member: {member.name}")
    return members


def extract_binaries(archive_path: Path, target: Path) -> list[dict[str, object]]:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = validate_archive_members(archive)
        target.mkdir(parents=True)
        rows = []
        for member in members:
            if not member.isfile():
                continue
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError(f"cannot read archive member: {member.name}")
            output = target / PurePosixPath(member.name).name
            with source, output.open("wb") as handle:
                shutil.copyfileobj(source, handle)
            os.chmod(output, member.mode & 0o777)
            rows.append(
                {
                    "path": output.name,
                    "bytes": output.stat().st_size,
                    "sha256": sha256_file(output),
                    "mode": oct(output.stat().st_mode & 0o777),
                }
            )
        return sorted(rows, key=lambda row: str(row["path"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    target = validate_path(args.target, ("AgentEnhance", "tools"))
    evidence_root = validate_path(args.evidence_root, ("AgentEnhance", "runs"))
    if target.exists() or evidence_root.exists():
        raise SystemExit("refusing existing tool target or evidence root")
    evidence_root.mkdir(parents=True)
    started_at = now()
    archive_path = evidence_root / ARCHIVE_NAME
    checksum_path = evidence_root / f"{ARCHIVE_NAME}.sha256"
    try:
        download(CHECKSUM_URL, checksum_path)
        if checksum_path.stat().st_size != CHECKSUM_BYTES:
            raise RuntimeError("checksum sidecar byte mismatch")
        if sha256_file(checksum_path) != CHECKSUM_SHA256:
            raise RuntimeError("checksum sidecar hash mismatch")
        sidecar = checksum_path.read_text(encoding="utf-8").strip().split()
        if sidecar != [ARCHIVE_SHA256, ARCHIVE_NAME]:
            raise RuntimeError("checksum sidecar content mismatch")
        download(ARCHIVE_URL, archive_path)
        if archive_path.stat().st_size != ARCHIVE_BYTES:
            raise RuntimeError("uv archive byte mismatch")
        if sha256_file(archive_path) != ARCHIVE_SHA256:
            raise RuntimeError("uv archive hash mismatch")
        binaries = extract_binaries(archive_path, target)
        if [row["path"] for row in binaries] != ["uv", "uvx"]:
            raise RuntimeError("expected exactly uv and uvx binaries")
        version = subprocess.check_output([str(target / "uv"), "--version"], text=True).strip()
        if version != f"uv {VERSION}":
            raise RuntimeError(f"uv version mismatch: {version}")
        result = {
            "schema_version": "agentenhance.uv_tool_materialization.v1",
            "status": "TERMINAL_ACCEPTED",
            "version": VERSION,
            "target_triple": TARGET_TRIPLE,
            "target": str(target),
            "started_at": started_at,
            "finished_at": now(),
            "archive": {
                "url": ARCHIVE_URL,
                "bytes": archive_path.stat().st_size,
                "sha256": sha256_file(archive_path),
            },
            "checksum_sidecar": {
                "url": CHECKSUM_URL,
                "bytes": checksum_path.stat().st_size,
                "sha256": sha256_file(checksum_path),
            },
            "binaries": binaries,
            "version_output": version,
        }
        record = evidence_root / "uv-tool-materialization.json"
        record.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        inventory = evidence_root / "EVIDENCE_SHA256SUMS"
        inventory.write_text(
            f"{sha256_file(record)}  {record}\n"
            f"{sha256_file(archive_path)}  {archive_path}\n"
            f"{sha256_file(checksum_path)}  {checksum_path}\n",
            encoding="utf-8",
        )
        (evidence_root / "TERMINAL_ACCEPTED").touch()
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "version": VERSION,
                    "archive_bytes": ARCHIVE_BYTES,
                    "binary_count": len(binaries),
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.uv_tool_materialization_failure.v1",
            "status": "TERMINAL_REJECTED",
            "version": VERSION,
            "target": str(target),
            "started_at": started_at,
            "finished_at": now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "partial_target_retained": target.exists(),
            "partial_archive_retained": archive_path.exists(),
            "cleanup_authorized": False,
        }
        record = evidence_root / "uv-tool-materialization-failure.json"
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
