#!/usr/bin/env python3
"""Create five deterministic, resumable archives for accepted WMA Wave-1 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


RUN_BASE = Path("/data1/2026/ldh/AgentEnhance/runs")
CONTROLLER = "wma-r1-wave1-controller-recovery1-20260903-v1"
SUMMARY = "wma-r1-wave1-three-seed-summaries-20260903-v1"
ARCHIVE_ROOT = Path("/data2/2026/ldh/AgentEnhance/archives/wma-r1-wave1-20260903-v1")
ARCHIVE_VOLUME = Path("/data2")
METHODS = (
    ("wma-mmfu-single", "mmfu_single"),
    ("wma-simplemem", "simplemem"),
    ("wma-m2a", "m2a"),
    ("wma-vilomem", "vilomem"),
)
SEEDS = (0, 1, 2)
WALL_TIME_CEILING_SECONDS = 24 * 60 * 60
ARCHIVE_STORAGE_CEILING_BYTES = 300 * 1024**3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inventory(root: Path, name: str = "SHA256SUMS") -> str:
    inventory = root / name
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


def tree_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def validate_sources() -> tuple[dict[str, Any], int]:
    controller_root = RUN_BASE / CONTROLLER
    if not (controller_root / "TERMINAL_ACCEPTED").is_file() or (
        controller_root / "TERMINAL_REJECTED"
    ).exists():
        raise RuntimeError("controller is not terminal-accepted")
    evidence: dict[str, Any] = {
        "controller": {
            "root": str(controller_root),
            "inventory_sha256": verify_inventory(controller_root),
        },
        "methods": {},
    }
    source_bytes = tree_bytes(controller_root)
    summary_root = RUN_BASE / SUMMARY
    if not (summary_root / "TERMINAL_ACCEPTED").is_file() or (
        summary_root / "TERMINAL_REJECTED"
    ).exists():
        raise RuntimeError("three-seed summary root is not terminal-accepted")
    summary_inventory = verify_inventory(summary_root)
    evidence["summary_root_inventory_sha256"] = summary_inventory
    source_bytes += tree_bytes(summary_root)

    for implementation_id, slug in METHODS:
        method_evidence = {"scheduler_roots": [], "aggregate_roots": []}
        for seed in SEEDS:
            scheduler = RUN_BASE / f"wma-r1-full-{slug}-seed{seed}-20260903-v1"
            aggregate = RUN_BASE / f"wma-r1-full-{slug}-seed{seed}-20260903-v1-aggregate"
            if not (scheduler / "SCHEDULER_EXECUTION_ACCEPTED").is_file() or (
                scheduler / "SCHEDULER_EXECUTION_WITH_REJECTIONS"
            ).exists():
                raise RuntimeError(f"scheduler is not accepted: {scheduler}")
            accepted_units = list((scheduler / "units").glob("*/TERMINAL_ACCEPTED"))
            rejected_units = list((scheduler / "units").glob("*/TERMINAL_REJECTED"))
            if len(accepted_units) != 150 or rejected_units:
                raise RuntimeError(f"scheduler unit cardinality mismatch: {scheduler}")
            scheduler_inventory = verify_inventory(scheduler, "SCHEDULER_SHA256SUMS")
            if not (aggregate / "TERMINAL_ACCEPTED").is_file() or (
                aggregate / "TERMINAL_REJECTED"
            ).exists():
                raise RuntimeError(f"aggregate is not accepted: {aggregate}")
            aggregate_inventory = verify_inventory(aggregate)
            method_evidence["scheduler_roots"].append(
                {
                    "seed": seed,
                    "root": str(scheduler),
                    "inventory_sha256": scheduler_inventory,
                    "accepted_units": 150,
                }
            )
            method_evidence["aggregate_roots"].append(
                {
                    "seed": seed,
                    "root": str(aggregate),
                    "inventory_sha256": aggregate_inventory,
                }
            )
            source_bytes += tree_bytes(scheduler) + tree_bytes(aggregate)
        child = summary_root / implementation_id
        if not (child / "TERMINAL_ACCEPTED").is_file() or (child / "TERMINAL_REJECTED").exists():
            raise RuntimeError(f"summary child is not accepted: {child}")
        method_evidence["summary"] = {
            "root": str(child),
            "inventory_sha256": verify_inventory(child),
        }
        evidence["methods"][implementation_id] = method_evidence
    return evidence, source_bytes


def members_for_method(implementation_id: str, slug: str) -> list[str]:
    members = []
    for seed in SEEDS:
        base = f"wma-r1-full-{slug}-seed{seed}-20260903-v1"
        members.extend((base, f"{base}-aggregate"))
    members.append(f"{SUMMARY}/{implementation_id}")
    return members


def create_archive(output: Path, members: list[str], timeout_seconds: float) -> dict[str, Any]:
    partial = output.with_suffix(output.suffix + ".partial")
    if output.exists() or partial.exists():
        raise RuntimeError(f"refusing existing archive target: {output}")
    command = [
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
        *members,
    ]
    subprocess.run(command, cwd=RUN_BASE, check=True, timeout=timeout_seconds)
    listing = subprocess.run(
        ["tar", "-I", "zstd -T1", "-tf", str(partial)],
        check=True,
        capture_output=True,
        text=True,
        timeout=min(timeout_seconds, 60 * 60),
    ).stdout.splitlines()
    if not listing:
        raise RuntimeError(f"empty archive listing: {partial}")
    prefixes = tuple(member.rstrip("/") + "/" for member in members)
    roots = set(members)
    unexpected = [name for name in listing if name.rstrip("/") not in roots and not name.startswith(prefixes)]
    if unexpected:
        raise RuntimeError(f"unexpected archive members: {unexpected[:10]}")
    os.replace(partial, output)
    return {
        "path": str(output),
        "bytes": output.stat().st_size,
        "sha256": sha256_file(output),
        "members": members,
        "archive_entries": len(listing),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-base", type=Path, default=RUN_BASE)
    parser.add_argument("--archive-root", type=Path, default=ARCHIVE_ROOT)
    args = parser.parse_args()
    if args.run_base != RUN_BASE or args.archive_root != ARCHIVE_ROOT:
        raise SystemExit("paths differ from the frozen Wave-1 archive contract")
    if ARCHIVE_ROOT.exists():
        raise SystemExit(f"refusing existing archive root: {ARCHIVE_ROOT}")
    if shutil.which("tar") is None or shutil.which("zstd") is None or shutil.which("ionice") is None:
        raise SystemExit("tar, zstd, and ionice are required")

    source_evidence, source_bytes = validate_sources()
    free_bytes = shutil.disk_usage(ARCHIVE_VOLUME).free
    required_headroom = min(ARCHIVE_STORAGE_CEILING_BYTES, source_bytes + 20 * 1024**3)
    if free_bytes < required_headroom:
        raise SystemExit(
            f"insufficient archive headroom: free={free_bytes} required={required_headroom}"
        )
    started = time.monotonic()
    ARCHIVE_ROOT.mkdir(parents=True)
    try:
        archives = {}
        for implementation_id, slug in METHODS:
            remaining = WALL_TIME_CEILING_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("archive stage exceeded its 24-hour ceiling")
            archives[implementation_id] = create_archive(
                ARCHIVE_ROOT / f"{implementation_id}.tar.zst",
                members_for_method(implementation_id, slug),
                remaining,
            )
        remaining = WALL_TIME_CEILING_SECONDS - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("archive stage exceeded its 24-hour ceiling")
        archives["controller"] = create_archive(
            ARCHIVE_ROOT / "wave1-controller-and-summary-index.tar.zst",
            [CONTROLLER, SUMMARY],
            remaining,
        )
        archive_bytes = sum(row["bytes"] for row in archives.values())
        if archive_bytes > ARCHIVE_STORAGE_CEILING_BYTES:
            raise RuntimeError(f"archive output exceeds 300 GiB ceiling: {archive_bytes}")
        manifest = {
            "schema_version": "agentenhance.wma_wave1_archive.v1",
            "status": "TERMINAL_ACCEPTED",
            "source_evidence": source_evidence,
            "source_bytes": source_bytes,
            "archive_bytes": archive_bytes,
            "archives": archives,
            "compression": "GNU tar deterministic metadata + zstd level 3 single-thread",
            "source_deleted": False,
            "models_deleted": False,
            "download_policy": "Use scripts/sftp_download_limited.sh at 4096 Kbit/s and verify each SHA-256 locally.",
        }
        manifest_path = ARCHIVE_ROOT / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        with (ARCHIVE_ROOT / "SHA256SUMS").open("w", encoding="utf-8") as handle:
            for row in archives.values():
                handle.write(f"{row['sha256']}  {Path(row['path']).name}\n")
            handle.write(f"{sha256_file(manifest_path)}  manifest.json\n")
        (ARCHIVE_ROOT / "TERMINAL_ACCEPTED").touch()
    except Exception as exc:
        (ARCHIVE_ROOT / "TERMINAL_REJECTED").write_text(
            json.dumps({"status": "TERMINAL_REJECTED", "error": repr(exc)}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
