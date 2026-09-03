#!/usr/bin/env python3
"""Archive the accepted Wave-1 30-row table projection after raw evidence archive."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path


RAW_ARCHIVE_ROOT = Path(
    "/data2/2026/ldh/AgentEnhance/archives/wma-r1-wave1-20260903-v1"
)
PROJECTION_ROOT = Path(
    "/data1/2026/ldh/AgentEnhance/runs/wma-r1-wave1-table-projection-20260904-v2"
)
ARCHIVE_ROOT = Path(
    "/data2/2026/ldh/AgentEnhance/archives/wma-r1-wave1-table-projection-20260904-v2"
)
ARCHIVE_VOLUME = Path("/data2")
WALL_TIME_CEILING_SECONDS = 2 * 60 * 60
ARCHIVE_STORAGE_CEILING_BYTES = 1024**3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inventory(root: Path) -> str:
    inventory = root / "SHA256SUMS"
    if not inventory.is_file():
        raise RuntimeError(f"missing inventory: {inventory}")
    for line in inventory.read_text(encoding="utf-8").splitlines():
        expected, raw_path = line.split(maxsplit=1)
        path = Path(raw_path.lstrip("*"))
        if not path.is_absolute():
            path = root / path
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"inventory mismatch: {path}")
    return sha256_file(inventory)


def validate_source(root: Path, schema_version: str) -> tuple[str, dict]:
    if not (root / "TERMINAL_ACCEPTED").is_file() or (root / "TERMINAL_REJECTED").exists():
        raise RuntimeError(f"source is not terminal-accepted: {root}")
    inventory_sha256 = verify_inventory(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "TERMINAL_ACCEPTED" or manifest.get(
        "schema_version"
    ) != schema_version:
        raise RuntimeError(f"source manifest mismatch: {root}")
    return inventory_sha256, manifest


def main() -> int:
    if ARCHIVE_ROOT.exists():
        raise SystemExit(f"refusing existing archive root: {ARCHIVE_ROOT}")
    if any(shutil.which(tool) is None for tool in ("tar", "zstd", "ionice")):
        raise SystemExit("tar, zstd, and ionice are required")
    raw_inventory_sha256, raw_manifest = validate_source(
        RAW_ARCHIVE_ROOT, "agentenhance.wma_wave1_archive.v1"
    )
    projection_inventory_sha256, projection_manifest = validate_source(
        PROJECTION_ROOT, "agentenhance.wma_wave1_table_projection.v2"
    )
    source_bytes = sum(path.stat().st_size for path in PROJECTION_ROOT.rglob("*") if path.is_file())
    if source_bytes > ARCHIVE_STORAGE_CEILING_BYTES:
        raise SystemExit(f"projection source exceeds 1 GiB ceiling: {source_bytes}")
    if shutil.disk_usage(ARCHIVE_VOLUME).free < source_bytes + 2 * 1024**3:
        raise SystemExit("insufficient data2 headroom for projection archive")
    ARCHIVE_ROOT.mkdir(parents=True)
    output = ARCHIVE_ROOT / "wma-r1-wave1-table-projection-20260904-v2.tar.zst"
    partial = output.with_suffix(output.suffix + ".partial")
    started = time.monotonic()
    try:
        subprocess.run(
            [
                "nice",
                "-n",
                "10",
                "ionice",
                "-c",
                "2",
                "-n",
                "7",
                "tar",
                "--sort=name",
                "--format=pax",
                "--pax-option=delete=atime,delete=ctime",
                "--mtime=@0",
                "--numeric-owner",
                "--owner=0",
                "--group=0",
                "-I",
                "zstd -T1 -3",
                "-cf",
                str(partial),
                PROJECTION_ROOT.name,
            ],
            cwd=PROJECTION_ROOT.parent,
            check=True,
            timeout=WALL_TIME_CEILING_SECONDS,
        )
        remaining = WALL_TIME_CEILING_SECONDS - (time.monotonic() - started)
        listing = subprocess.run(
            ["tar", "-I", "zstd -T1", "-tf", str(partial)],
            check=True,
            capture_output=True,
            text=True,
            timeout=max(1, remaining),
        ).stdout.splitlines()
        prefix = PROJECTION_ROOT.name + "/"
        if not listing or any(name.rstrip("/") != PROJECTION_ROOT.name and not name.startswith(prefix) for name in listing):
            raise RuntimeError("projection archive contains an unexpected member")
        os.replace(partial, output)
        archive_sha256 = sha256_file(output)
        manifest = {
            "schema_version": "agentenhance.wma_wave1_projection_archive.v2",
            "status": "TERMINAL_ACCEPTED",
            "raw_archive_root": str(RAW_ARCHIVE_ROOT),
            "raw_archive_inventory_sha256": raw_inventory_sha256,
            "raw_archive_bytes": raw_manifest.get("archive_bytes"),
            "projection_root": str(PROJECTION_ROOT),
            "projection_inventory_sha256": projection_inventory_sha256,
            "accepted_implementations": projection_manifest.get("accepted_implementations"),
            "source_bytes": source_bytes,
            "archive": {
                "path": str(output),
                "bytes": output.stat().st_size,
                "sha256": archive_sha256,
                "entries": len(listing),
            },
            "source_deleted": False,
            "models_deleted": False,
            "download_policy": "Use scripts/sftp_download_limited.sh at 4096 Kbit/s and verify SHA-256 locally.",
        }
        manifest_path = ARCHIVE_ROOT / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (ARCHIVE_ROOT / "SHA256SUMS").write_text(
            f"{archive_sha256}  {output.name}\n"
            f"{sha256_file(manifest_path)}  manifest.json\n",
            encoding="utf-8",
        )
        (ARCHIVE_ROOT / "TERMINAL_ACCEPTED").touch()
    except Exception as exc:
        (ARCHIVE_ROOT / "TERMINAL_REJECTED").write_text(
            json.dumps({"status": "TERMINAL_REJECTED", "error": repr(exc)}, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        raise
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
