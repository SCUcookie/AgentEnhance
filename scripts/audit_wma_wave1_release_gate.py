#!/usr/bin/env python3
"""Read-only, fail-closed release audit for WMA Wave1 recovery2."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Mapping, Sequence


METHODS = ("MMFU_Single", "SimpleMem", "M2A", "ViLoMem")
METHOD_SLUGS = {
    "MMFU_Single": "mmfu_single",
    "SimpleMem": "simplemem",
    "M2A": "m2a",
    "ViLoMem": "vilomem",
}
SEEDS = (0, 1, 2)
EXPECTED_UNITS = 150
EXPECTED_SESSIONS = 2761
EXPECTED_QA = 7906
UNIT_INVENTORY_SHA256 = "027f2c3f757d99cb098a6e1887ac7bc837f726031368a4c758970ee90db33f39"
DATASET_MANIFEST_SHA256 = "9f63a71631ddb2ba506ba4927e4a69e31b8c857a6b72fbd70153201673c8a2cb"
WMA_SOURCE_COMMIT = "15ea25b723d9c4fb35e8062037aec6a5601e4442"
CONTROLLER_NAME = "wma-r1-wave1-controller-recovery2-20260904-v1"
RUN_ID_TEMPLATE = "wma-r1-full-{slug}-seed{seed}-recovery2-20260904-v1"
PACKAGE_ROOT = "/data1/2026/ldh/AgentEnhance/incoming/wma-r1-wave1-full-recovery1-20260903-v1-control"
PACKAGE_MANIFEST_SHA256 = "4d3433dd616b938e431c68e807358c4d9b55719345660f3f97bae293fb5ce361"
RECOVERY_FULL_SCHEDULER_SHA256 = "2df8a4eee3b0a3c121fea863e7f555d55ee2c50646c1cbf7d51700c6e0b1793b"
BLOCKED_PROCESS_TOKENS = (
    "remote_wma_wave1_controller",
    "remote_wma_full_method",
    "run_wma_seeded.py",
    "remote_wma_one_shot_unit",
    "aggregate_wma_one_shot_units.py",
    "vllm.entrypoints.openai.api_server",
)
BLOCKED_PORTS = frozenset({18113, 18114, 18120})
MIN_DATA1_FREE_BYTES = 40 * 1024**3
ARCHIVE_RESERVE_BYTES = 10 * 1024**3


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def verify_sha256_inventory(
    root: Path, *, inventory_name: str = "SHA256SUMS", exact_members: set[str] | None = None
) -> int:
    inventory = root / inventory_name
    _require(inventory.is_file() and not inventory.is_symlink(), f"missing SHA256SUMS: {root}")
    resolved_root = root.resolve()
    observed: set[str] = set()
    for line in inventory.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        parts = line.split(maxsplit=1)
        _require(len(parts) == 2 and _is_sha256(parts[0]), f"malformed SHA256SUMS: {root}")
        candidate = Path(parts[1].lstrip("*"))
        if not candidate.is_absolute():
            candidate = root / candidate
        _require(not candidate.is_symlink(), f"linked inventory member: {candidate}")
        resolved = candidate.resolve()
        try:
            relative = resolved.relative_to(resolved_root).as_posix()
        except ValueError as exc:
            raise RuntimeError(f"SHA256SUMS member escapes root: {candidate}") from exc
        _require(relative not in observed, f"duplicate SHA256SUMS member: {relative}")
        _require(resolved.is_file() and not resolved.is_symlink(), f"missing inventory member: {resolved}")
        _require(sha256_file(resolved) == parts[0], f"inventory digest mismatch: {resolved}")
        observed.add(relative)
    _require(bool(observed), f"empty SHA256SUMS: {root}")
    if exact_members is not None:
        _require(observed == exact_members, f"SHA256SUMS surface drift: {root}")
    return len(observed)


def load_unit_names(path: Path) -> list[str]:
    _require(path.is_file() and not path.is_symlink(), "unit inventory is missing or linked")
    _require(sha256_file(path) == UNIT_INVENTORY_SHA256, "unit inventory digest mismatch")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    _require(len(rows) == EXPECTED_UNITS, "unit inventory denominator drift")
    names = [f"{int(row['sample_index']):03d}_{row['sample_id']}" for row in rows]
    _require(len(set(names)) == EXPECTED_UNITS, "unit inventory contains duplicate names")
    return names


def parse_key_values(path: Path) -> dict[str, str]:
    _require(path.is_file() and not path.is_symlink(), f"key-value record is missing or linked: {path}")
    payload: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        _require("=" in line, "malformed controller identity line")
        key, value = line.split("=", 1)
        _require(key and key not in payload, f"duplicate controller identity key: {key}")
        payload[key] = value
    return payload


def parse_identity(path: Path) -> dict[str, str]:
    payload = parse_key_values(path)
    expected = {
        "methods": ",".join(METHODS),
        "seeds": "0,1,2",
        "package_root": PACKAGE_ROOT,
        "package_manifest_sha256": PACKAGE_MANIFEST_SHA256,
        "recovery_controller": "remote_wma_wave1_controller_recovery2.sh",
        "recovery_full_scheduler_sha256": RECOVERY_FULL_SCHEDULER_SHA256,
        "chat_gpu_memory_utilization": "0.90",
        "parent_evidence_reused": "false",
    }
    for key, value in expected.items():
        _require(payload.get(key) == value, f"controller identity drift: {key}")
    _require("started_at" in payload, "controller started_at is missing")
    return payload


def expected_progress() -> list[tuple[str, int, str]]:
    return [
        (method, seed, RUN_ID_TEMPLATE.format(slug=METHOD_SLUGS[method], seed=seed))
        for method in METHODS
        for seed in SEEDS
    ]


def verify_progress(path: Path) -> list[dict[str, str]]:
    _require(path.is_file() and not path.is_symlink(), "controller progress is missing or linked")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        headers = tuple(reader.fieldnames or ())
    _require(
        headers == ("method", "seed", "run_id", "scheduler_status", "aggregate_status", "finished_at"),
        "controller progress schema drift",
    )
    _require(len(rows) == len(expected_progress()), "controller progress denominator drift")
    for row, (method, seed, run_id) in zip(rows, expected_progress()):
        _require(row["method"] == method, "controller method order drift")
        _require(row["seed"] == str(seed), "controller seed order drift")
        _require(row["run_id"] == run_id, "controller run identity drift")
        _require(row["scheduler_status"] == "ACCEPTED", "scheduler status is not accepted")
        _require(row["aggregate_status"] == "ACCEPTED", "aggregate status is not accepted")
        _require(bool(row["finished_at"]), "controller progress lacks finished_at")
    return rows


def proc_cmdlines(proc_root: Path = Path("/proc")) -> list[str]:
    rows: list[str] = []
    own_pid = os.getpid()
    if not proc_root.is_dir():
        return rows
    for entry in proc_root.iterdir():
        if not entry.name.isdigit() or int(entry.name) == own_pid:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError, IsADirectoryError):
            continue
        text = raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
        if text:
            rows.append(text)
    return rows


def listening_ports(proc_net_root: Path = Path("/proc/net")) -> set[int]:
    ports: set[int] = set()
    for name in ("tcp", "tcp6"):
        path = proc_net_root / name
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[1:]
        except (FileNotFoundError, PermissionError):
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 4 or fields[3] != "0A":
                continue
            try:
                ports.add(int(fields[1].rsplit(":", 1)[1], 16))
            except (IndexError, ValueError) as exc:
                raise RuntimeError(f"malformed socket table row in {path}") from exc
    return ports


def tmux_sessions() -> list[str]:
    completed = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError("tmux session audit failed")
    return [line for line in completed.stdout.splitlines() if line]


def tree_bytes(roots: Iterable[Path]) -> int:
    total = 0
    for root in roots:
        for path in root.rglob("*"):
            _require(not path.is_symlink(), f"symlink in accepted evidence tree: {path}")
            if path.is_file():
                total += path.stat().st_size
    return total


def audit_release(
    *,
    controller_root: Path,
    run_base: Path,
    unit_inventory: Path,
    future_roots: Sequence[Path],
    command_lines: Iterable[str],
    observed_ports: set[int],
    observed_tmux_sessions: Sequence[str],
    data1_free_bytes: int,
    data2_free_bytes: int,
) -> dict[str, object]:
    _require(controller_root.name == CONTROLLER_NAME, "unexpected Wave1 controller identity")
    _require(controller_root.is_dir() and not controller_root.is_symlink(), "controller root is missing or linked")
    controller_accepted = controller_root / "TERMINAL_ACCEPTED"
    _require(controller_accepted.is_file() and not controller_accepted.is_symlink(), "controller is not terminal accepted")
    _require(not (controller_root / "TERMINAL_REJECTED").exists(), "controller rejection marker is present")
    parse_identity(controller_root / "identity.txt")
    progress = verify_progress(controller_root / "progress.csv")
    controller_members = verify_sha256_inventory(
        controller_root, exact_members={"identity.txt", "progress.csv"}
    )
    unit_names = load_unit_names(unit_inventory)

    evidence_roots: list[Path] = [controller_root]
    unit_inventory_members = 0
    for row in progress:
        run_root = run_base / row["run_id"]
        aggregate_root = run_base / f"{row['run_id']}-aggregate"
        _require(run_root.is_dir() and not run_root.is_symlink(), f"run root is missing or linked: {run_root}")
        scheduler_accepted = run_root / "SCHEDULER_EXECUTION_ACCEPTED"
        _require(scheduler_accepted.is_file() and not scheduler_accepted.is_symlink(), f"scheduler not accepted: {run_root}")
        _require(
            not (run_root / "SCHEDULER_EXECUTION_WITH_REJECTIONS").exists(),
            f"scheduler rejection marker is present: {run_root}",
        )
        summary = parse_key_values(run_root / "scheduler-summary.txt")
        _require(summary.get("accepted") == str(EXPECTED_UNITS), "scheduler accepted denominator drift")
        _require(summary.get("rejected") == "0", "scheduler rejected-unit count is nonzero")
        _require(summary.get("infrastructure_failure") == "0", "scheduler infrastructure failure is nonzero")
        with (run_root / "rejected-units.csv").open(encoding="utf-8", newline="") as handle:
            rejected_rows = list(csv.DictReader(handle))
        _require(not rejected_rows, f"scheduler rejected-units ledger is nonempty: {run_root}")
        units_root = run_root / "units"
        observed_units = sorted(path.name for path in units_root.iterdir() if path.is_dir())
        _require(observed_units == sorted(unit_names), f"unit surface drift: {run_root}")
        for name in unit_names:
            unit_root = units_root / name
            unit_accepted = unit_root / "TERMINAL_ACCEPTED"
            _require(unit_accepted.is_file() and not unit_accepted.is_symlink(), f"unit not accepted: {unit_root}")
            _require(not (unit_root / "TERMINAL_REJECTED").exists(), f"unit rejected: {unit_root}")
            unit_inventory_members += verify_sha256_inventory(unit_root)
        verify_sha256_inventory(run_root, inventory_name="SCHEDULER_SHA256SUMS")
        _require(
            aggregate_root.is_dir() and not aggregate_root.is_symlink(),
            f"aggregate root is missing or linked: {aggregate_root}",
        )
        aggregate_accepted = aggregate_root / "TERMINAL_ACCEPTED"
        _require(aggregate_accepted.is_file() and not aggregate_accepted.is_symlink(), f"aggregate not accepted: {aggregate_root}")
        _require(not (aggregate_root / "TERMINAL_REJECTED").exists(), f"aggregate rejected: {aggregate_root}")
        aggregate = json.loads((aggregate_root / "audit.json").read_text(encoding="utf-8"))
        _require(aggregate.get("status") == "TERMINAL_ACCEPTED", "aggregate audit is not accepted")
        _require(aggregate.get("baseline") == row["method"], "aggregate method drift")
        _require(aggregate.get("seed") == int(row["seed"]), "aggregate seed drift")
        _require(aggregate.get("n_expected") == EXPECTED_UNITS, "aggregate expected denominator drift")
        _require(aggregate.get("n_observed") == EXPECTED_UNITS, "aggregate observed denominator drift")
        _require(aggregate.get("n_failed") == 0, "aggregate contains failed units")
        _require(aggregate.get("n_sessions") == EXPECTED_SESSIONS, "aggregate session denominator drift")
        _require(aggregate.get("n_qa") == EXPECTED_QA, "aggregate QA denominator drift")
        _require(aggregate.get("main_comparison_eligible") is True, "aggregate is not comparison eligible")
        _require(aggregate.get("inventory_sha256") == UNIT_INVENTORY_SHA256, "aggregate inventory identity drift")
        _require(aggregate.get("source_commit") == WMA_SOURCE_COMMIT, "aggregate source identity drift")
        _require(aggregate.get("dataset_manifest_sha256") == DATASET_MANIFEST_SHA256, "aggregate dataset identity drift")
        verify_sha256_inventory(aggregate_root)
        evidence_roots.extend((run_root, aggregate_root))

    offenders = sorted({
        line for line in command_lines if any(token in line for token in BLOCKED_PROCESS_TOKENS)
    })
    _require(not offenders, f"Wave1 process remains active: {offenders[0] if offenders else ''}")
    blocked_ports = sorted(BLOCKED_PORTS.intersection(observed_ports))
    _require(not blocked_ports, f"Wave1 port remains listening: {blocked_ports}")
    blocked_tmux = sorted(name for name in observed_tmux_sessions if name.startswith("agentenhance-wma-"))
    _require(not blocked_tmux, f"Wave1 tmux session remains: {blocked_tmux[0] if blocked_tmux else ''}")
    collisions = sorted(str(path) for path in future_roots if path.exists())
    _require(not collisions, f"future fresh root already exists: {collisions[0] if collisions else ''}")
    _require(data1_free_bytes >= MIN_DATA1_FREE_BYTES, "data1 free space below 40 GiB")
    source_bytes = tree_bytes(evidence_roots)
    required_data2 = source_bytes + ARCHIVE_RESERVE_BYTES
    _require(data2_free_bytes >= required_data2, "data2 archive headroom is insufficient")
    return {
        "schema_version": "agentenhance.wma_wave1_release_gate_audit.v1",
        "status": "TERMINAL_ACCEPTED",
        "controller_root": str(controller_root),
        "methods": len(METHODS),
        "seeds": len(SEEDS),
        "method_seed_runs": len(progress),
        "accepted_units": len(progress) * EXPECTED_UNITS,
        "accepted_qa": len(progress) * EXPECTED_QA,
        "controller_inventory_members": controller_members,
        "unit_inventory_members_verified": unit_inventory_members,
        "unit_hashes_verified": True,
        "blocked_processes": 0,
        "blocked_ports": [],
        "blocked_tmux_sessions": [],
        "future_root_collisions": [],
        "source_evidence_bytes": source_bytes,
        "data1_free_bytes": data1_free_bytes,
        "data2_free_bytes": data2_free_bytes,
        "required_data2_free_bytes": required_data2,
        "scores_observed": 0,
        "official_values_used": False,
        "mutation_performed": False,
    }


def validate_project_root(path: Path) -> Path:
    _require(not path.is_symlink(), "remote root must not be a symlink")
    resolved = path.resolve()
    _require(path.is_absolute() and resolved.name == "AgentEnhance", "remote root must be absolute AgentEnhance")
    _require(len(resolved.parts) > 2 and resolved.parts[1] in {"data1", "data2"}, "remote root must be under data1 or data2")
    _require(resolved.is_dir(), "remote root is missing")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data1-root", type=Path, required=True)
    parser.add_argument("--data2-root", type=Path, required=True)
    parser.add_argument("--unit-inventory", type=Path, required=True)
    args = parser.parse_args()
    try:
        data1_root = validate_project_root(args.data1_root)
        data2_root = validate_project_root(args.data2_root)
        _require(data1_root.parts[1] == "data1", "--data1-root is not under /data1")
        _require(data2_root.parts[1] == "data2", "--data2-root is not under /data2")
        future_roots = (
            data1_root / "runs/wma-r1-wave1-three-seed-summaries-recovery2-20260904-v1",
            data1_root / "runs/wma-r1-wave1-table-projection-recovery2-20260904-v3",
            data1_root / "runs/wma-r1-wave1-local-result-admission-recovery2-20260904-v1",
            data2_root / "archives/wma-r1-wave1-recovery2-20260904-v1",
            data2_root / "archives/wma-r1-wave1-table-projection-recovery2-20260904-v3",
            data2_root / "archives/wma-r1-wave1-failure-history-20260904-v1",
        )
        report = audit_release(
            controller_root=data1_root / f"runs/{CONTROLLER_NAME}",
            run_base=data1_root / "runs",
            unit_inventory=args.unit_inventory.resolve(),
            future_roots=future_roots,
            command_lines=proc_cmdlines(),
            observed_ports=listening_ports(),
            observed_tmux_sessions=tmux_sessions(),
            data1_free_bytes=shutil.disk_usage(data1_root).free,
            data2_free_bytes=shutil.disk_usage(data2_root).free,
        )
    except Exception as exc:
        print(json.dumps({
            "schema_version": "agentenhance.wma_wave1_release_gate_audit.v1",
            "status": "TERMINAL_REJECTED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "scores_observed": 0,
            "mutation_performed": False,
        }, sort_keys=True), file=sys.stderr)
        return 4
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
