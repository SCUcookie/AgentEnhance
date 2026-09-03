#!/usr/bin/env python3
"""Combine the four predeclared WMA smoke results without promoting them."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


IMPLEMENTATIONS = (
    "wma-mmfu-single",
    "wma-simplemem",
    "wma-m2a",
    "wma-vilomem",
)

METRICS = {
    "qa_correct_ratio": "question_answering.correct_ratio",
    "qa_hallucination_ratio": "question_answering.hallucination_ratio",
    "qa_omission_ratio": "question_answering.omission_ratio",
    "answer_f1": "question_answering.answer_matching.avg_f1",
    "answer_bleu1": "question_answering.answer_matching.avg_bleu1",
    "retrieval_recall_at_10": "question_answering.retrieval_ranking.recall_at.10",
    "retrieval_ndcg_at_10": "question_answering.retrieval_ranking.ndcg_at.10",
    "memory_avg_recall": "memory_recall.avg_recall",
    "memory_avg_correctness": "memory_correctness.avg_correctness",
    "memory_update_handling": "update_handling.score",
    "memory_interference_rejection": "interference_rejection.score",
    "total_tokens": "token_usage.total.total_tokens",
    "end_to_end_seconds": "timing.total_seconds",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise SystemExit(f"refusing existing output directory: {output_dir}")
    if run_root not in output_dir.parents:
        raise SystemExit("output directory must be inside the development run root")

    records = []
    result_hashes: dict[str, str] = {}
    for implementation_id in IMPLEMENTATIONS:
        path = run_root / "results" / f"{implementation_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") != "ACCEPTED_DEVELOPMENT":
            raise SystemExit(f"unaccepted result: {implementation_id}")
        if payload.get("main_comparison_eligible") is not False:
            raise SystemExit(f"development result is main-table eligible: {implementation_id}")
        if payload.get("implementation_id") != implementation_id:
            raise SystemExit(f"implementation ID mismatch: {implementation_id}")
        if payload.get("sample_ids") != ["mobile_05"]:
            raise SystemExit(f"sample mismatch: {implementation_id}")
        if (payload.get("n_samples"), payload.get("n_sessions"), payload.get("n_qa"), payload.get("n_failed")) != (1, 11, 13, 0):
            raise SystemExit(f"denominator mismatch: {implementation_id}")
        metrics = payload["metrics"]
        row = {"implementation_id": implementation_id}
        for display_name, metric_path in METRICS.items():
            if metric_path not in metrics:
                raise SystemExit(f"missing {metric_path}: {implementation_id}")
            row[display_name] = metrics[metric_path]
        row["artifact_inventory_sha256"] = payload["artifact_inventory_sha256"]
        records.append(row)
        result_hashes[implementation_id] = sha256_file(path)

    output_dir.mkdir(parents=True)
    csv_path = output_dir / "summary.csv"
    fieldnames = ["implementation_id", *METRICS, "artifact_inventory_sha256"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    audit = {
        "schema_version": "agentenhance.wma_development_summary.v1",
        "status": "ACCEPTED_DEVELOPMENT",
        "evidence_role": "development-foundation",
        "main_comparison_eligible": False,
        "run_id": "wma-r1-real-sample-smoke-20260903-v1",
        "benchmark_id": "worldmemarena-2026",
        "track_id": "wma-lifecycle-matched-v1",
        "sample_id": "mobile_05",
        "sample_index": 100,
        "n_samples_per_method": 1,
        "n_sessions_per_method": 11,
        "n_qa_per_method": 13,
        "methods": list(IMPLEMENTATIONS),
        "metric_projection": METRICS,
        "result_file_sha256": result_hashes,
        "summary_csv_sha256": sha256_file(csv_path),
        "claim_boundary": "Single-sample smoke results validate execution and expose descriptive tradeoffs only; they are not estimates of benchmark performance or SOTA evidence."
    }
    audit_path = output_dir / "audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": audit["status"],
        "methods": len(records),
        "summary_csv_sha256": audit["summary_csv_sha256"],
        "audit_sha256": sha256_file(audit_path),
        "output_dir": str(output_dir),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
