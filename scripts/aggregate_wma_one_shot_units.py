#!/usr/bin/env python3
"""Independently audit and aggregate 150 accepted one-shot WMA units."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def assert_finite(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            assert_finite(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_finite(child, f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise SystemExit(f"non-finite numeric value at {path}: {value}")


def percentile(values: list[float], quantile: float) -> float:
    """Return the linearly interpolated sample percentile (Hyndman-Fan type 7)."""
    if not values:
        raise SystemExit("cannot calculate a percentile over an empty sequence")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def verify_inventory(unit_root: Path) -> str:
    inventory = unit_root / "SHA256SUMS"
    for line in inventory.read_text(encoding="utf-8").splitlines():
        expected, raw_path = line.split(maxsplit=1)
        path = Path(raw_path.lstrip("*"))
        if not path.is_file() or sha256_file(path) != expected:
            raise SystemExit(f"unit inventory mismatch: {path}")
    return sha256_file(inventory)


def slice_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluations = [row["eval"] for row in rows]
    labels = [ev.get("answer_label") for ev in evaluations]
    valid = [label for label in labels if label in {"Correct", "Hallucination", "Omission"}]
    denom = len(valid)
    avg = lambda key: mean(float(ev.get(key, 0.0) or 0.0) for ev in evaluations) if evaluations else 0.0
    return {
        "n_total": len(rows),
        "n_valid": denom,
        "correct_ratio": sum(label == "Correct" for label in valid) / denom if denom else 0.0,
        "hallucination_ratio": sum(label == "Hallucination" for label in valid) / denom if denom else 0.0,
        "omission_ratio": sum(label == "Omission" for label in valid) / denom if denom else 0.0,
        "answer_f1": avg("answer_f1"),
        "answer_bleu1": avg("answer_bleu1"),
        "retrieval_hit_rate": avg("retrieval_hit_rate"),
        "retrieval_recall_at_10": mean(
            float((ev.get("retrieval_recall_at") or {}).get("10", 0.0) or 0.0)
            for ev in evaluations
        ) if evaluations else 0.0,
        "retrieval_ndcg_at_10": mean(
            float((ev.get("retrieval_ndcg_at") or {}).get("10", 0.0) or 0.0)
            for ev in evaluations
        ) if evaluations else 0.0,
    }


def load_question_metadata(dataset_root: Path, sample_ids: set[str]) -> dict[tuple[str, str, str], dict[str, str]]:
    out: dict[tuple[str, str, str], dict[str, str]] = {}
    for path in sorted(dataset_root.rglob("*.json")):
        if path.name in {"small_ids.json", "dataset-manifest.json"} or path.parent == dataset_root:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        sample_id = str(payload.get("sample_id") or "")
        if sample_id not in sample_ids:
            continue
        parts = path.relative_to(dataset_root).parts
        for checkpoint in payload.get("qa_checkpoints") or []:
            checkpoint_id = str(checkpoint.get("checkpoint_id") or "")
            for question in checkpoint.get("questions") or []:
                modalities: set[str] = set()
                for evidence in question.get("evidence") or []:
                    if evidence.get("memory_id"):
                        modalities.add("memory")
                    if evidence.get("image_id"):
                        modalities.add("image")
                key = (sample_id, checkpoint_id, str(question.get("question") or ""))
                if key in out:
                    raise SystemExit(f"duplicate question metadata key: {key}")
                out[key] = {
                    "scope": parts[0],
                    "task_family": "/".join(parts[:2]),
                    "subcategory": "/".join(parts[:-1]),
                    "difficulty": str(question.get("difficulty") or "UNKNOWN"),
                    "evidence_modality": "+".join(sorted(modalities)) or "none",
                    "question_type": str(question.get("question_type_abbrev") or "UNKNOWN"),
                }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wma-repo", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--inventory-sha256", required=True)
    parser.add_argument("--units-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()

    if args.output_root.exists():
        raise SystemExit(f"refusing existing aggregate root: {args.output_root}")
    if sha256_file(args.inventory) != args.inventory_sha256:
        raise SystemExit("run-unit inventory digest mismatch")
    sys.path.insert(0, str(args.wma_repo.resolve()))
    from eval_framework.evaluators.aggregate import aggregate_metrics

    with args.inventory.open(encoding="utf-8", newline="") as handle:
        inventory_rows = list(csv.DictReader(handle))
    if len(inventory_rows) != 150:
        raise SystemExit(f"expected 150 inventory rows, found {len(inventory_rows)}")

    all_sessions: list[dict[str, Any]] = []
    all_qa: list[dict[str, Any]] = []
    unit_manifest: list[dict[str, Any]] = []
    timing = {"pipeline_seconds": 0.0, "eval_seconds": 0.0, "total_seconds": 0.0}
    peak_rss_kib = 0
    memory_storage_bytes = 0

    for row in inventory_rows:
        index = int(row["sample_index"])
        sample_id = row["sample_id"]
        unit_root = args.units_root / f"{index:03d}_{sample_id}"
        if not (unit_root / "TERMINAL_ACCEPTED").is_file() or (unit_root / "TERMINAL_REJECTED").exists():
            raise SystemExit(f"unit not accepted: {unit_root}")
        inventory_digest = verify_inventory(unit_root)
        sessions = read_jsonl(unit_root / "output/session_records.jsonl")
        qa = read_jsonl(unit_root / "output/qa_records.jsonl")
        if len(sessions) != int(row["sessions"]) or len(qa) != int(row["qa"]):
            raise SystemExit(f"record count mismatch: {unit_root}")
        if {str(record.get("sample_id")) for record in [*sessions, *qa]} != {sample_id}:
            raise SystemExit(f"sample ID mismatch: {unit_root}")
        if any(record.get("eval") is None for record in [*sessions, *qa]):
            raise SystemExit(f"missing evaluation: {unit_root}")
        source_path = args.dataset_root / row["relative_json_path"]
        if sha256_file(source_path) != row["source_json_sha256"]:
            raise SystemExit(f"source JSON mismatch: {source_path}")

        per_unit_aggregate = json.loads((unit_root / "output/aggregate_metrics.json").read_text(encoding="utf-8"))
        for key in timing:
            timing[key] += float((per_unit_aggregate.get("timing") or {}).get(key, 0.0) or 0.0)
        resource_text = (unit_root / "resource-usage.txt").read_text(encoding="utf-8", errors="replace")
        match = re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", resource_text)
        if match:
            peak_rss_kib = max(peak_rss_kib, int(match.group(1)))
        storage_root = unit_root / "baseline-storage"
        memory_storage_bytes += sum(path.stat().st_size for path in storage_root.rglob("*") if path.is_file())
        all_sessions.extend(sessions)
        all_qa.extend(qa)
        unit_manifest.append({
            "sample_index": index,
            "sample_id": sample_id,
            "sessions": len(sessions),
            "qa": len(qa),
            "unit_root": str(unit_root),
            "artifact_inventory_sha256": inventory_digest,
        })

    if len(all_sessions) != 2761 or len(all_qa) != 7906:
        raise SystemExit(f"full denominator mismatch: sessions={len(all_sessions)} qa={len(all_qa)}")
    aggregate = aggregate_metrics(
        args.baseline,
        session_evaluations=[record["eval"] for record in all_sessions],
        qa_evaluations=[record["eval"] for record in all_qa],
    )
    aggregate["timing"] = {key: round(value, 2) for key, value in timing.items()}

    retrieval_latencies = [float(record["eval"]["retrieval_seconds"]) for record in all_qa]
    answer_latencies = [float(record["eval"]["answer_seconds"]) for record in all_qa]
    pipeline_latencies = [retrieval + answer for retrieval, answer in zip(retrieval_latencies, answer_latencies)]
    monitor_path = args.units_root.parent / "evidence" / "gpu-monitor.csv"
    if not monitor_path.is_file():
        raise SystemExit(f"missing scheduler GPU monitor: {monitor_path}")
    monitored_memory: dict[int, dict[int, int]] = defaultdict(dict)
    with monitor_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            timestamp = int(row["timestamp_unix"])
            gpu_index = int(row["gpu_index"])
            if gpu_index not in {1, 3, 4, 5}:
                raise SystemExit(f"unexpected monitored GPU index: {gpu_index}")
            monitored_memory[timestamp][gpu_index] = int(row["memory_used_mib"])
    if not monitored_memory or any(set(values) != {1, 3, 4, 5} for values in monitored_memory.values()):
        raise SystemExit("incomplete scheduler GPU monitor samples")
    monitor_timestamps = sorted(monitored_memory)
    peak_allocated_vram_mib = max(sum(values.values()) for values in monitored_memory.values())
    monitoring_seconds = monitor_timestamps[-1] - monitor_timestamps[0]
    aggregate["derived_runtime"] = {
        "definition": "user-facing retrieval plus answer generation; post-hoc evaluator latency excluded",
        "end_to_end_seconds": timing["pipeline_seconds"],
        "retrieval_latency_p50_ms": percentile(retrieval_latencies, 0.50) * 1000.0,
        "retrieval_latency_p95_ms": percentile(retrieval_latencies, 0.95) * 1000.0,
        "end_to_end_latency_p50_ms": percentile(pipeline_latencies, 0.50) * 1000.0,
        "end_to_end_latency_p95_ms": percentile(pipeline_latencies, 0.95) * 1000.0,
    }
    aggregate["derived_resources"] = {
        "memory_storage_bytes": memory_storage_bytes,
        "peak_driver_ram_gib": peak_rss_kib / 1024 / 1024,
        "peak_allocated_vram_gib": peak_allocated_vram_mib / 1024,
        "allocated_gpu_hours": monitoring_seconds * 4 / 3600,
        "gpu_monitor_interval_seconds": 5,
        "gpu_monitor_indices": [1, 3, 4, 5],
        "gpu_monitor_observed_seconds": monitoring_seconds,
    }

    sample_ids = {row["sample_id"] for row in inventory_rows}
    question_meta = load_question_metadata(args.dataset_root, sample_ids)
    buckets: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for record in all_qa:
        key = (str(record["sample_id"]), str(record["checkpoint_id"]), str(record["question"]))
        metadata = question_meta.get(key)
        if metadata is None:
            raise SystemExit(f"missing question metadata: {key}")
        for family, value in metadata.items():
            buckets[family][value].append(record)
    slices = {
        family: {value: slice_summary(records) for value, records in sorted(values.items())}
        for family, values in sorted(buckets.items())
    }
    slice_denominator = sum(v["n_total"] for v in slices["question_type"].values())
    if slice_denominator != 7906:
        raise SystemExit(f"slice denominator mismatch: {slice_denominator}")
    assert_finite(aggregate, "aggregate")
    assert_finite(slices, "slices")

    args.output_root.mkdir(parents=True)
    (args.output_root / "aggregate_metrics.json").write_text(
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_root / "slice_metrics.json").write_text(
        json.dumps(slices, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for name, records in (("session_records.jsonl", all_sessions), ("qa_records.jsonl", all_qa)):
        with (args.output_root / name).open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    with (args.output_root / "unit-manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(unit_manifest[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(unit_manifest)
    audit = {
        "schema_version": "agentenhance.wma_full_method_audit.v1",
        "status": "TERMINAL_ACCEPTED",
        "main_comparison_eligible": True,
        "baseline": args.baseline,
        "seed": args.seed,
        "n_expected": 150,
        "n_observed": 150,
        "n_failed": 0,
        "n_sessions": len(all_sessions),
        "n_qa": len(all_qa),
        "peak_driver_rss_gib": peak_rss_kib / 1024 / 1024,
        "memory_storage_bytes": memory_storage_bytes,
        "peak_allocated_vram_gib": peak_allocated_vram_mib / 1024,
        "allocated_gpu_hours": monitoring_seconds * 4 / 3600,
        "inventory_sha256": args.inventory_sha256,
        "source_commit": "15ea25b723d9c4fb35e8062037aec6a5601e4442",
        "dataset_manifest_sha256": "9f63a71631ddb2ba506ba4927e4a69e31b8c857a6b72fbd70153201673c8a2cb",
    }
    (args.output_root / "audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    files = sorted(path for path in args.output_root.rglob("*") if path.is_file())
    with (args.output_root / "SHA256SUMS").open("w", encoding="utf-8") as handle:
        for path in files:
            handle.write(f"{sha256_file(path)}  {path}\n")
    (args.output_root / "TERMINAL_ACCEPTED").touch()
    print(json.dumps(audit, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
