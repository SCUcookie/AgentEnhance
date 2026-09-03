#!/usr/bin/env python3
"""Combine exactly three accepted WMA seed aggregates without selecting metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, stdev
from typing import Any


EXPECTED_SEEDS = {0, 1, 2}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inventory(root: Path) -> str:
    inventory = root / "SHA256SUMS"
    if not inventory.is_file():
        raise SystemExit(f"missing aggregate inventory: {inventory}")
    for line in inventory.read_text(encoding="utf-8").splitlines():
        expected, raw_path = line.split(maxsplit=1)
        path = Path(raw_path.lstrip("*"))
        if not path.is_file() or sha256_file(path) != expected:
            raise SystemExit(f"aggregate inventory mismatch: {path}")
    return sha256_file(inventory)


def flatten_numeric(value: Any, prefix: str = "") -> dict[str, float]:
    output: dict[str, float] = {}
    if isinstance(value, dict):
        for key, child in sorted(value.items()):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            output.update(flatten_numeric(child, child_prefix))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if not math.isfinite(numeric):
            raise SystemExit(f"non-finite metric: {prefix}={value}")
        output[prefix] = numeric
    return output


def combine_numeric(seed_payloads: dict[int, dict[str, float]]) -> dict[str, dict[str, Any]]:
    key_sets = {seed: set(payload) for seed, payload in seed_payloads.items()}
    first_keys = next(iter(key_sets.values()))
    if any(keys != first_keys for keys in key_sets.values()):
        detail = {seed: sorted(first_keys ^ keys)[:20] for seed, keys in key_sets.items()}
        raise SystemExit(f"numeric metric schema differs across seeds: {detail}")
    combined: dict[str, dict[str, Any]] = {}
    for key in sorted(first_keys):
        values = {str(seed): seed_payloads[seed][key] for seed in sorted(seed_payloads)}
        ordered = [values[str(seed)] for seed in sorted(seed_payloads)]
        combined[key] = {
            "mean": mean(ordered),
            "sample_standard_deviation": stdev(ordered),
            "seed_values": values,
        }
    return combined


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--implementation-id", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--aggregate-root", type=Path, action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    if len(args.aggregate_root) != 3:
        raise SystemExit("exactly three --aggregate-root values are required")
    if args.output_root.exists():
        raise SystemExit(f"refusing existing output root: {args.output_root}")

    aggregate_by_seed: dict[int, dict[str, float]] = {}
    slices_by_seed: dict[int, dict[str, float]] = {}
    source_evidence: list[dict[str, Any]] = []
    for root in args.aggregate_root:
        if not (root / "TERMINAL_ACCEPTED").is_file() or (root / "TERMINAL_REJECTED").exists():
            raise SystemExit(f"aggregate root is not terminal-accepted: {root}")
        inventory_sha256 = verify_inventory(root)
        audit = json.loads((root / "audit.json").read_text(encoding="utf-8"))
        if audit.get("status") != "TERMINAL_ACCEPTED" or not audit.get("main_comparison_eligible"):
            raise SystemExit(f"aggregate audit not eligible: {root}")
        if audit.get("baseline") != args.baseline:
            raise SystemExit(f"baseline mismatch: {root}")
        if (audit.get("n_observed"), audit.get("n_failed"), audit.get("n_qa")) != (150, 0, 7906):
            raise SystemExit(f"denominator mismatch: {root}")
        seed = int(audit["seed"])
        if seed in aggregate_by_seed:
            raise SystemExit(f"duplicate seed: {seed}")
        aggregate_by_seed[seed] = flatten_numeric(
            json.loads((root / "aggregate_metrics.json").read_text(encoding="utf-8"))
        )
        slices_by_seed[seed] = flatten_numeric(
            json.loads((root / "slice_metrics.json").read_text(encoding="utf-8"))
        )
        source_evidence.append({
            "seed": seed,
            "aggregate_root": str(root.resolve()),
            "artifact_inventory_sha256": inventory_sha256,
        })
    if set(aggregate_by_seed) != EXPECTED_SEEDS:
        raise SystemExit(f"expected seeds {sorted(EXPECTED_SEEDS)}, found {sorted(aggregate_by_seed)}")

    args.output_root.mkdir(parents=True)
    summary = {
        "schema_version": "agentenhance.wma_method_seed_summary.v1",
        "status": "TERMINAL_ACCEPTED",
        "main_comparison_eligible": True,
        "run_id": args.run_id,
        "implementation_id": args.implementation_id,
        "run_id": args.run_id,
        "baseline": args.baseline,
        "seed_count": 3,
        "seeds": [0, 1, 2],
        "n_samples": 150,
        "n_qa": 7906,
        "metrics": combine_numeric(aggregate_by_seed),
        "source_evidence": sorted(source_evidence, key=lambda row: row["seed"]),
    }
    slice_summary = {
        "schema_version": "agentenhance.wma_slice_seed_summary.v1",
        "implementation_id": args.implementation_id,
        "run_id": args.run_id,
        "baseline": args.baseline,
        "seed_count": 3,
        "metrics": combine_numeric(slices_by_seed),
    }
    (args.output_root / "method-seed-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_root / "slice-seed-summary.json").write_text(
        json.dumps(slice_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    audit = {
        "schema_version": "agentenhance.wma_method_seed_combine_audit.v1",
        "status": "TERMINAL_ACCEPTED",
        "implementation_id": args.implementation_id,
        "baseline": args.baseline,
        "seed_count": 3,
        "seed_set": [0, 1, 2],
        "n_samples": 150,
        "n_qa": 7906,
        "metric_selection": "none; every finite numeric aggregate and frozen slice field was combined",
    }
    (args.output_root / "audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    files = sorted(path for path in args.output_root.iterdir() if path.is_file())
    with (args.output_root / "SHA256SUMS").open("w", encoding="utf-8") as handle:
        for path in files:
            handle.write(f"{sha256_file(path)}  {path}\n")
    (args.output_root / "TERMINAL_ACCEPTED").touch()
    print(json.dumps(audit, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
