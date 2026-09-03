#!/usr/bin/env python3
"""Audit and combine the frozen 4-method x 3-seed WMA Wave-1 run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


CONTROLLER_ROOT = Path(
    "/data1/2026/ldh/AgentEnhance/runs/"
    "wma-r1-wave1-controller-recovery1-20260903-v1"
)
RUN_BASE = Path("/data1/2026/ldh/AgentEnhance/runs")
OUTPUT_ROOT = RUN_BASE / "wma-r1-wave1-three-seed-summaries-20260903-v1"
COMBINE_SCRIPT_SHA256 = "2030a7dfa9673e3a9d865ceabfec67c80ce9e40b44a27ab51f961e66c2d92d23"
METHODS = (
    ("MMFU_Single", "mmfu_single", "wma-mmfu-single"),
    ("SimpleMem", "simplemem", "wma-simplemem"),
    ("M2A", "m2a", "wma-m2a"),
    ("ViLoMem", "vilomem", "wma-vilomem"),
)
SEEDS = (0, 1, 2)
WALL_TIME_CEILING_SECONDS = 4 * 60 * 60
OUTPUT_STORAGE_CEILING_BYTES = 2 * 1024**3


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


def expected_progress_rows() -> set[tuple[str, str, str, str, str]]:
    return {
        (
            baseline,
            str(seed),
            f"wma-r1-full-{slug}-seed{seed}-20260903-v1",
            "ACCEPTED",
            "ACCEPTED",
        )
        for baseline, slug, _ in METHODS
        for seed in SEEDS
    }


def validate_controller() -> str:
    if not (CONTROLLER_ROOT / "TERMINAL_ACCEPTED").is_file():
        raise RuntimeError("Wave-1 controller is not terminal-accepted")
    if (CONTROLLER_ROOT / "TERMINAL_REJECTED").exists():
        raise RuntimeError("Wave-1 controller has a rejection marker")
    inventory_sha256 = verify_inventory(CONTROLLER_ROOT)
    with (CONTROLLER_ROOT / "progress.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    observed = {
        (
            row["method"],
            row["seed"],
            row["run_id"],
            row["scheduler_status"],
            row["aggregate_status"],
        )
        for row in rows
    }
    if len(rows) != 12 or observed != expected_progress_rows():
        raise RuntimeError("controller progress is not the exact frozen 4x3 accepted matrix")
    return inventory_sha256


def validate_aggregate(root: Path, baseline: str, seed: int) -> str:
    if not (root / "TERMINAL_ACCEPTED").is_file() or (root / "TERMINAL_REJECTED").exists():
        raise RuntimeError(f"aggregate is not terminal-accepted: {root}")
    inventory_sha256 = verify_inventory(root)
    audit = json.loads((root / "audit.json").read_text(encoding="utf-8"))
    required = {
        "status": "TERMINAL_ACCEPTED",
        "main_comparison_eligible": True,
        "baseline": baseline,
        "seed": seed,
        "n_expected": 150,
        "n_observed": 150,
        "n_failed": 0,
        "n_qa": 7906,
        "source_commit": "15ea25b723d9c4fb35e8062037aec6a5601e4442",
        "dataset_manifest_sha256": "9f63a71631ddb2ba506ba4927e4a69e31b8c857a6b72fbd70153201673c8a2cb",
    }
    for key, expected in required.items():
        if audit.get(key) != expected:
            raise RuntimeError(f"aggregate audit mismatch: {root}:{key}")
    for required_file in (
        "aggregate_metrics.json",
        "slice_metrics.json",
        "qa_records.jsonl",
        "session_records.jsonl",
        "unit-manifest.csv",
    ):
        if not (root / required_file).is_file():
            raise RuntimeError(f"missing retained aggregate evidence: {root / required_file}")
    return inventory_sha256


def build_plan() -> list[dict[str, Any]]:
    plan = []
    for baseline, slug, implementation_id in METHODS:
        aggregate_roots = [
            RUN_BASE / f"wma-r1-full-{slug}-seed{seed}-20260903-v1-aggregate"
            for seed in SEEDS
        ]
        plan.append(
            {
                "baseline": baseline,
                "slug": slug,
                "implementation_id": implementation_id,
                "run_id": f"wma-r1-three-seed-{slug.replace('_', '-')}-20260903-v1",
                "aggregate_roots": aggregate_roots,
                "output_root": OUTPUT_ROOT / implementation_id,
            }
        )
    return plan


def validate_wave1_process_exit() -> None:
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        check=False,
        capture_output=True,
        text=True,
    )
    sessions = set(result.stdout.splitlines()) if result.returncode == 0 else set()
    forbidden_sessions = {"agentenhance-wma-wave1-controller-r1"}
    for _, slug, _ in METHODS:
        session_slug = slug.replace("_", "-")
        for seed in SEEDS:
            suffix = f"full-{session_slug}-s{seed}-v1"
            forbidden_sessions.update(
                {
                    f"agentenhance-wma-chat-{suffix}",
                    f"agentenhance-wma-e1024-{suffix}",
                    f"agentenhance-wma-e384-{suffix}",
                }
            )
    active = sorted(sessions & forbidden_sessions)
    if active:
        raise RuntimeError(f"Wave-1 tmux sessions still active: {active}")
    processes = subprocess.run(
        ["ps", "-eo", "cmd"], check=True, capture_output=True, text=True
    ).stdout.splitlines()
    forbidden_tokens = [CONTROLLER_ROOT.name] + [
        f"wma-r1-full-{slug}-seed{seed}-20260903-v1"
        for _, slug, _ in METHODS
        for seed in SEEDS
    ]
    active_processes = [
        command
        for command in processes
        if any(token in command for token in forbidden_tokens)
    ]
    if active_processes:
        raise RuntimeError(f"Wave-1 processes still active: {active_processes[:5]}")


def main() -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser()
    parser.add_argument("--combine-script", type=Path, required=True)
    parser.add_argument("--controller-root", type=Path, default=CONTROLLER_ROOT)
    parser.add_argument("--run-base", type=Path, default=RUN_BASE)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    if args.controller_root != CONTROLLER_ROOT or args.run_base != RUN_BASE or args.output_root != OUTPUT_ROOT:
        raise SystemExit("paths differ from the frozen Wave-1 postprocess contract")
    if sha256_file(args.combine_script) != COMBINE_SCRIPT_SHA256:
        raise SystemExit("combine script digest mismatch")
    if OUTPUT_ROOT.exists():
        raise SystemExit(f"refusing existing postprocess root: {OUTPUT_ROOT}")

    controller_inventory_sha256 = validate_controller()
    validate_wave1_process_exit()
    plan = build_plan()
    aggregate_evidence: dict[str, list[dict[str, Any]]] = {}
    for item in plan:
        aggregate_evidence[item["implementation_id"]] = [
            {
                "seed": seed,
                "root": str(root),
                "inventory_sha256": validate_aggregate(root, item["baseline"], seed),
            }
            for seed, root in zip(SEEDS, item["aggregate_roots"])
        ]

    OUTPUT_ROOT.mkdir(parents=True)
    try:
        for item in plan:
            command = [
                sys.executable,
                str(args.combine_script),
                "--run-id",
                item["run_id"],
                "--implementation-id",
                item["implementation_id"],
                "--baseline",
                item["baseline"],
            ]
            for root in item["aggregate_roots"]:
                command.extend(("--aggregate-root", str(root)))
            command.extend(("--output-root", str(item["output_root"])))
            remaining = WALL_TIME_CEILING_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("Wave-1 postprocess exceeded its four-hour ceiling")
            subprocess.run(command, check=True, timeout=remaining)
        children = {}
        for item in plan:
            child = item["output_root"]
            if not (child / "TERMINAL_ACCEPTED").is_file() or (child / "TERMINAL_REJECTED").exists():
                raise RuntimeError(f"three-seed summary rejected: {child}")
            children[item["implementation_id"]] = {
                "root": str(child),
                "inventory_sha256": verify_inventory(child),
                "aggregate_evidence": aggregate_evidence[item["implementation_id"]],
            }
        manifest = {
            "schema_version": "agentenhance.wma_wave1_postprocess.v1",
            "status": "TERMINAL_ACCEPTED",
            "selection": "none; all four frozen methods and all three seeds are retained",
            "controller_root": str(CONTROLLER_ROOT),
            "controller_inventory_sha256": controller_inventory_sha256,
            "combine_script_sha256": COMBINE_SCRIPT_SHA256,
            "children": children,
            "official_values_used": False,
            "next_gate": "project fixed statistical tables from all four summaries without inspecting values",
        }
        manifest_path = OUTPUT_ROOT / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        output_bytes = sum(path.stat().st_size for path in OUTPUT_ROOT.rglob("*") if path.is_file())
        if output_bytes > OUTPUT_STORAGE_CEILING_BYTES:
            raise RuntimeError(
                f"postprocess output exceeded 2 GiB ceiling: {output_bytes} bytes"
            )
        files = sorted(
            path
            for path in OUTPUT_ROOT.rglob("*")
            if path.is_file() and path.name not in {"SHA256SUMS", "TERMINAL_ACCEPTED", "TERMINAL_REJECTED"}
        )
        with (OUTPUT_ROOT / "SHA256SUMS").open("w", encoding="utf-8") as handle:
            for path in files:
                handle.write(f"{sha256_file(path)}  {path}\n")
        (OUTPUT_ROOT / "TERMINAL_ACCEPTED").touch()
    except Exception as exc:
        (OUTPUT_ROOT / "TERMINAL_REJECTED").write_text(
            json.dumps({"status": "TERMINAL_REJECTED", "error": repr(exc)}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
