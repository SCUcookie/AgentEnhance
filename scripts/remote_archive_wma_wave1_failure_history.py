#!/usr/bin/env python3
"""Archive Wave1 rejected and capability-gate evidence separately from results."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


RUN_BASE = Path("/data1/2026/ldh/AgentEnhance/runs")
ARCHIVE_ROOT = Path(
    "/data2/2026/ldh/AgentEnhance/archives/"
    "wma-r1-wave1-failure-history-20260904-v1"
)
RECOVERY2_CONTROLLER = RUN_BASE / "wma-r1-wave1-controller-recovery2-20260904-v1"
SOURCE_ROOTS = {
    "initial_controller_rejection": RUN_BASE / "wma-r1-wave1-controller-20260903-v1",
    "recovery1_controller_rejection": RUN_BASE
    / "wma-r1-wave1-controller-recovery1-20260903-v1",
    "recovery1_failed_seed": RUN_BASE / "wma-r1-full-mmfu_single-seed0-20260903-v1",
    "recovery2_wrong_path_capability": RUN_BASE
    / "wma-r1-oom-capability-css03-recovery2-20260904-v1",
    "recovery2_accepted_capability": RUN_BASE
    / "wma-r1-oom-capability-css03-recovery2-recovery1-20260904-v1",
}
MAX_SOURCE_BYTES = 2 * 1024**3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_inventory(root: Path, name: str = "SHA256SUMS") -> str:
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


def scan_root(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        raise RuntimeError(f"missing source root: {root}")
    files = sorted(path for path in root.rglob("*") if path.is_file())
    symlinks = sorted(path for path in root.rglob("*") if path.is_symlink())
    if symlinks:
        raise RuntimeError(f"source contains symlinks: {root}")
    tree = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        tree.update(relative.encode("utf-8"))
        tree.update(b"\0")
        tree.update(sha256_file(path).encode("ascii"))
        tree.update(b"\n")
    return {
        "path": str(root),
        "regular_files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "tree_sha256": tree.hexdigest(),
    }


def require_terminal_quiescence() -> str:
    accepted = (RECOVERY2_CONTROLLER / "TERMINAL_ACCEPTED").is_file()
    rejected = (RECOVERY2_CONTROLLER / "TERMINAL_REJECTED").is_file()
    if accepted == rejected:
        raise RuntimeError("recovery2 controller is not in exactly one terminal state")
    completed = subprocess.run(
        ["tmux", "list-sessions"],
        check=False,
        capture_output=True,
        text=True,
    )
    sessions = completed.stdout if completed.returncode == 0 else ""
    active = [line for line in sessions.splitlines() if line.startswith("agentenhance-")]
    if active:
        raise RuntimeError(f"project tmux sessions remain active: {active}")
    return "TERMINAL_ACCEPTED" if accepted else "TERMINAL_REJECTED"


def validate_sources() -> dict[str, dict[str, Any]]:
    first = SOURCE_ROOTS["initial_controller_rejection"]
    recovery1 = SOURCE_ROOTS["recovery1_controller_rejection"]
    failed_seed = SOURCE_ROOTS["recovery1_failed_seed"]
    wrong_path = SOURCE_ROOTS["recovery2_wrong_path_capability"]
    capability = SOURCE_ROOTS["recovery2_accepted_capability"]
    for controller in (first, recovery1):
        if not (controller / "TERMINAL_REJECTED").is_file():
            raise RuntimeError(f"controller rejection marker missing: {controller}")
    if not (failed_seed / "SCHEDULER_EXECUTION_WITH_REJECTIONS").is_file():
        raise RuntimeError("recovery1 failed seed marker missing")
    if len(list((failed_seed / "units").glob("*/TERMINAL_ACCEPTED"))) != 71:
        raise RuntimeError("recovery1 accepted-unit count mismatch")
    if len(list((failed_seed / "units").glob("*/TERMINAL_REJECTED"))) != 1:
        raise RuntimeError("recovery1 rejected-unit count mismatch")
    scheduler_inventory = validate_inventory(failed_seed, "SCHEDULER_SHA256SUMS")
    if not (wrong_path / "TERMINAL_REJECTED").is_file():
        raise RuntimeError("wrong-path capability rejection marker missing")
    forbidden_wrong_path = {
        "aggregate_metrics.json",
        "session-records.jsonl",
        "qa-records.jsonl",
        "audit.json",
    }
    if any((wrong_path / name).exists() for name in forbidden_wrong_path):
        raise RuntimeError("wrong-path capability unexpectedly contains numeric artifacts")
    if not (capability / "TERMINAL_ACCEPTED").is_file() or (
        capability / "TERMINAL_REJECTED"
    ).exists():
        raise RuntimeError("corrected capability is not terminal-accepted")
    capability_inventory = validate_inventory(capability)
    records = {name: scan_root(root) for name, root in SOURCE_ROOTS.items()}
    records["recovery1_failed_seed"]["inventory_sha256"] = scheduler_inventory
    records["recovery2_accepted_capability"]["inventory_sha256"] = capability_inventory
    if sum(record["bytes"] for record in records.values()) > MAX_SOURCE_BYTES:
        raise RuntimeError("failure-history source exceeds 2 GiB ceiling")
    return records


def write_inventory() -> str:
    files = sorted(
        path
        for path in ARCHIVE_ROOT.rglob("*")
        if path.is_file()
        and path.name not in {"SHA256SUMS", "TERMINAL_ACCEPTED", "TERMINAL_REJECTED"}
    )
    inventory = ARCHIVE_ROOT / "SHA256SUMS"
    inventory.write_text(
        "".join(f"{sha256_file(path)}  {path}\n" for path in files),
        encoding="utf-8",
    )
    return sha256_file(inventory)


def main() -> int:
    if ARCHIVE_ROOT.exists():
        raise SystemExit(f"refusing existing archive root: {ARCHIVE_ROOT}")
    recovery2_status = require_terminal_quiescence()
    source_records = validate_sources()
    ARCHIVE_ROOT.mkdir(parents=True)
    try:
        evidence_root = ARCHIVE_ROOT / "evidence"
        evidence_root.mkdir()
        for name, source in SOURCE_ROOTS.items():
            shutil.copytree(source, evidence_root / name, copy_function=shutil.copy2)
        copied_records = {name: scan_root(evidence_root / name) for name in SOURCE_ROOTS}
        for name in SOURCE_ROOTS:
            if any(
                source_records[name][field] != copied_records[name][field]
                for field in ("regular_files", "bytes", "tree_sha256")
            ):
                raise RuntimeError(f"copied source shape mismatch: {name}")
        manifest = {
            "schema_version": "agentenhance.wma_wave1_failure_history_archive.v1",
            "status": "TERMINAL_ACCEPTED",
            "recovery2_controller_status_at_archive": recovery2_status,
            "evidence_role": "failure diagnosis and infrastructure capability history only",
            "main_comparison_eligible": False,
            "source_roots": source_records,
            "copied_roots": copied_records,
            "numeric_result_rows_admitted": 0,
            "source_reported_results_used": False,
            "source_deletion_authorized": False,
        }
        (ARCHIVE_ROOT / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        inventory_sha256 = write_inventory()
        validate_inventory(ARCHIVE_ROOT)
        (ARCHIVE_ROOT / "TERMINAL_ACCEPTED").touch()
        print(
            json.dumps(
                {
                    "status": "TERMINAL_ACCEPTED",
                    "archive_root": str(ARCHIVE_ROOT),
                    "source_roots": len(SOURCE_ROOTS),
                    "source_bytes": sum(row["bytes"] for row in source_records.values()),
                    "inventory_sha256": inventory_sha256,
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as error:
        (ARCHIVE_ROOT / "failure.txt").write_text(f"{type(error).__name__}: {error}\n")
        (ARCHIVE_ROOT / "TERMINAL_REJECTED").touch()
        raise


if __name__ == "__main__":
    raise SystemExit(main())
