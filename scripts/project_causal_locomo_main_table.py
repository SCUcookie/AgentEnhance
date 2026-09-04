#!/usr/bin/env python3
"""Project one complete local Causal-LoCoMo summary into its fixed table.

This module is result-free infrastructure.  It rejects partial, development,
official, synthetic, non-finite, or protocol-leaking summaries and never ranks
methods or emits a superiority claim.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence


METHOD_ORDER = (
    "cmi-no-memory",
    "cmi-full-history",
    "cmi-vector-memory",
    "cmi-summary-memory",
    "cmi-reflection-memory",
    "cmi-graph-memory",
    "cmi",
)
ELIGIBLE_METHODS = frozenset({
    "cmi-no-memory", "cmi-full-history", "cmi-vector-memory",
    "cmi-summary-memory", "cmi-graph-memory",
})
BLOCKED_METHODS = frozenset({"cmi-reflection-memory", "cmi"})
AGENTENHANCE_METHOD = "agentenhance-ceu"
QUALITY_METRICS = (
    "task_score", "passes", "useful_memory_precision", "useful_memory_recall",
    "useful_memory_f1", "harmful_memory_rejection_rate",
    "irrelevant_memory_rejection_rate", "outdated_memory_rejection_rate",
    "context_dependent_memory_accuracy", "poisoned_memory_adoption_rate",
    "false_positive_memory_acceptance_rate", "false_negative_memory_rejection_rate",
    "harmful_instruction_following_rate",
)
COST_METRICS = (
    "endpoint_calls", "failed_endpoint_calls", "prompt_tokens", "completion_tokens",
    "total_tokens", "wall_seconds", "selected_memory_count", "retrieved_memory_count",
)
TABLE_METRIC_MAP = {
    "task_score": "task_score",
    "task_success_rate": "passes",
    "useful_memory_precision": "useful_memory_precision",
    "useful_memory_recall": "useful_memory_recall",
    "useful_memory_f1": "useful_memory_f1",
    "harmful_memory_rejection_rate": "harmful_memory_rejection_rate",
    "irrelevant_memory_rejection_rate": "irrelevant_memory_rejection_rate",
    "outdated_memory_rejection_rate": "outdated_memory_rejection_rate",
    "context_dependent_memory_accuracy": "context_dependent_memory_accuracy",
    "poisoned_memory_adoption_rate": "poisoned_memory_adoption_rate",
    "false_positive_memory_acceptance_rate": "false_positive_memory_acceptance_rate",
    "false_negative_memory_rejection_rate": "false_negative_memory_rejection_rate",
    "harmful_instruction_following_rate": "harmful_instruction_following_rate",
    "endpoint_calls": "endpoint_calls",
    "failed_endpoint_calls": "failed_endpoint_calls",
    "prompt_tokens": "prompt_tokens",
    "completion_tokens": "completion_tokens",
    "total_tokens": "total_tokens",
    "wall_seconds": "wall_seconds",
    "selected_memory_count": "selected_memory_count",
    "retrieved_memory_count": "retrieved_memory_count",
}
EXPECTED_ROWS_PER_METHOD = 261
EXPECTED_ROWS_TOTAL = 1827
EXPECTED_BLOCKED_ROWS = 522
EXPECTED_QID_ORDER_SHA256 = "d97ad01180c998454c413ee26f1229c4ae115f082bf30664f8318836e3a10021"


class ProjectionError(RuntimeError):
    """A summary or table violates the prospective admission contract."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _verify_inventory(root: Path) -> str:
    inventory = root / "SHA256SUMS"
    if not inventory.is_file() or inventory.is_symlink():
        raise ProjectionError("evaluation root lacks a regular SHA256SUMS")
    observed: set[str] = set()
    for line in inventory.read_text(encoding="utf-8").splitlines():
        if len(line) < 67 or line[64:66] != "  ":
            raise ProjectionError("malformed evaluation inventory")
        digest, relative = line[:64], line[66:]
        path = Path(relative)
        if (
            len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest)
            or path.is_absolute() or ".." in path.parts or relative in observed
        ):
            raise ProjectionError("unsafe evaluation inventory member")
        member = root / path
        if not member.is_file() or member.is_symlink() or _sha256_file(member) != digest:
            raise ProjectionError(f"evaluation inventory mismatch: {relative}")
        observed.add(relative)
    if observed != {"audit.json", "scores.jsonl", "summary.json"}:
        raise ProjectionError("evaluation inventory member set drift")
    return _sha256_file(inventory)


def _finite(value: object, field: str, *, unit_interval: bool) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ProjectionError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (unit_interval and result > 1):
        raise ProjectionError(f"{field} is outside its frozen range")
    return result


def _render(value: float) -> str:
    return format(value, ".17g")


def load_template(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    expected = list(METHOD_ORDER) + [AGENTENHANCE_METHOD]
    if [row.get("method_id") for row in rows] != expected:
        raise ProjectionError("fixed table method order drift")
    if any(column not in fields for column in TABLE_METRIC_MAP):
        raise ProjectionError("fixed table metric surface drift")
    if any(row[column] for row in rows for column in TABLE_METRIC_MAP):
        raise ProjectionError("fixed table already contains result values")
    return fields, rows


def validate_summary(summary: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if (
        summary.get("schema_version") != "agentenhance.causal_locomo_evaluation_summary.v1"
        or summary.get("mode") != "real"
        or summary.get("registered_rows") != EXPECTED_ROWS_TOTAL
        or summary.get("accepted_rows", -1) + summary.get("failed_rows", -1) != EXPECTED_ROWS_TOTAL
        or summary.get("protocol_blocked_rows") != EXPECTED_BLOCKED_ROWS
        or summary.get("failure_imputation") != {"higher_is_better": 0.0, "lower_is_better": 1.0}
    ):
        raise ProjectionError("summary identity, denominator, mode, or failure policy drift")
    by_method_raw = summary.get("by_method")
    if not isinstance(by_method_raw, list):
        raise ProjectionError("summary lacks by_method rows")
    by_method = {row.get("method_id"): row for row in by_method_raw if isinstance(row, Mapping)}
    if set(by_method) != set(METHOD_ORDER) or len(by_method_raw) != len(METHOD_ORDER):
        raise ProjectionError("summary method surface drift")
    for method_id in METHOD_ORDER:
        row = by_method[method_id]
        if (
            row.get("registered_rows") != EXPECTED_ROWS_PER_METHOD
            or row.get("accepted_rows", -1) + row.get("failed_rows", -1) != EXPECTED_ROWS_PER_METHOD
        ):
            raise ProjectionError(f"method denominator drift: {method_id}")
        costs = row.get("cost_metrics")
        if not isinstance(costs, Mapping) or set(costs) != set(COST_METRICS):
            raise ProjectionError(f"cost metric surface drift: {method_id}")
        for metric in COST_METRICS:
            _finite(costs[metric], f"{method_id}.{metric}", unit_interval=False)
        if method_id in BLOCKED_METHODS:
            if (
                row.get("comparison_status") != "PROTOCOL_BLOCKED"
                or row.get("accepted_rows") != 0
                or row.get("failed_rows") != EXPECTED_ROWS_PER_METHOD
                or row.get("protocol_blocked_rows") != EXPECTED_ROWS_PER_METHOD
                or row.get("metrics") is not None
                or any(float(costs[metric]) != 0.0 for metric in COST_METRICS)
            ):
                raise ProjectionError(f"protocol blocker drift: {method_id}")
        else:
            metrics = row.get("metrics")
            if (
                row.get("comparison_status") != "ELIGIBLE"
                or row.get("protocol_blocked_rows") != 0
                or not isinstance(metrics, Mapping)
                or set(metrics) != set(QUALITY_METRICS)
            ):
                raise ProjectionError(f"eligible method surface drift: {method_id}")
            for metric in QUALITY_METRICS:
                _finite(metrics[metric], f"{method_id}.{metric}", unit_interval=True)
    return by_method


def _normalized_group(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> dict[tuple[Any, ...], dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(tuple(row[field] for field in fields), []).append(row)
    output: dict[tuple[Any, ...], dict[str, Any]] = {}
    for key, group in groups.items():
        blocked = all(row["comparison_status"] == "PROTOCOL_BLOCKED" for row in group)
        output[key] = {
            **{field: value for field, value in zip(fields, key)},
            "registered_rows": len(group),
            "accepted_rows": sum(row["prediction_status"] == "ACCEPTED" for row in group),
            "failed_rows": sum(row["prediction_status"] == "FAILED" for row in group),
            "protocol_blocked_rows": sum(row["comparison_status"] == "PROTOCOL_BLOCKED" for row in group),
            "comparison_status": "PROTOCOL_BLOCKED" if blocked else "ELIGIBLE",
            "metrics": None if blocked else {
                metric: sum(float(row["metrics"][metric]) for row in group) / len(group)
                for metric in QUALITY_METRICS
            },
            "cost_metrics": {
                metric: sum(float(row["cost_metrics"][metric]) for row in group) / len(group)
                for metric in COST_METRICS
            },
        }
    return output


def _summary_groups(rows: object, fields: Sequence[str]) -> dict[tuple[Any, ...], Mapping[str, Any]]:
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ProjectionError("summary grouped rows are malformed")
    output = {tuple(row.get(field) for field in fields): row for row in rows}
    if len(output) != len(rows):
        raise ProjectionError("summary grouped rows contain duplicates")
    return output


def load_evaluation_root(
    root: Path,
    *,
    expected_qid_order_sha256: str = EXPECTED_QID_ORDER_SHA256,
) -> tuple[dict[str, Any], str]:
    """Independently reconcile a terminal real evaluator root before projection."""
    if (
        not root.is_absolute() or root.is_symlink() or not root.is_dir()
        or not (root / "TERMINAL_ACCEPTED").is_file()
        or (root / "TERMINAL_ACCEPTED").is_symlink()
        or (root / "TERMINAL_REJECTED").exists()
    ):
        raise ProjectionError("evaluation root is not terminal-accepted and path-safe")
    inventory_sha256 = _verify_inventory(root)
    try:
        audit = json.loads((root / "audit.json").read_text(encoding="utf-8"))
        summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
        scores = [json.loads(line) for line in (root / "scores.jsonl").read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectionError(f"cannot parse evaluation evidence: {exc}") from exc
    if not isinstance(audit, Mapping) or not isinstance(summary, Mapping):
        raise ProjectionError("evaluation audit and summary must be objects")
    if (
        audit.get("schema_version") != "agentenhance.causal_locomo_evaluation_audit.v1"
        or audit.get("qid_order_sha256") != expected_qid_order_sha256
        or audit.get("raw_rows") != EXPECTED_ROWS_TOTAL
        or audit.get("score_rows") != EXPECTED_ROWS_TOTAL
        or audit.get("missing_rows") != 0
        or audit.get("dropped_failed_rows") != 0
        or audit.get("official_values_used") is not False
    ):
        raise ProjectionError("evaluation audit identity or denominator drift")
    by_method = validate_summary(summary)
    if len(scores) != EXPECTED_ROWS_TOTAL:
        raise ProjectionError("score row denominator drift")
    qid_order: list[str] = []
    seen_keys: set[tuple[int, str, str]] = set()
    for seed in (0, 1, 2):
        start = seed * 87 * len(METHOD_ORDER)
        seed_rows = scores[start:start + 87 * len(METHOD_ORDER)]
        seed_qids: list[str] = []
        for qid_index in range(87):
            group = seed_rows[qid_index * len(METHOD_ORDER):(qid_index + 1) * len(METHOD_ORDER)]
            if len(group) != len(METHOD_ORDER):
                raise ProjectionError("score qid group cardinality drift")
            qid = group[0].get("example_id") if isinstance(group[0], Mapping) else None
            if not isinstance(qid, str) or not qid or any(row.get("example_id") != qid for row in group):
                raise ProjectionError("score qid order drift")
            if [row.get("method_id") for row in group] != list(METHOD_ORDER):
                raise ProjectionError("score method order drift")
            seed_qids.append(qid)
        if seed == 0:
            qid_order = seed_qids
        elif seed_qids != qid_order:
            raise ProjectionError("score qid order differs across seeds")
    if hashlib.sha256(("\n".join(qid_order) + "\n").encode("utf-8")).hexdigest() != expected_qid_order_sha256:
        raise ProjectionError("score qid order hash drift")
    task_family_by_qid: dict[str, str] = {}
    for row in scores:
        if not isinstance(row, Mapping) or row.get("schema_version") != "agentenhance.causal_locomo_score.v1":
            raise ProjectionError("score row schema drift")
        seed, qid, method = row.get("seed"), row.get("example_id"), row.get("method_id")
        key = (seed, qid, method)
        if seed not in {0, 1, 2} or method not in METHOD_ORDER or key in seen_keys:
            raise ProjectionError("score row identity duplicate or drift")
        seen_keys.add(key)
        task_family = row.get("task_family")
        if not isinstance(task_family, str) or not task_family:
            raise ProjectionError("score row lacks task_family")
        if qid in task_family_by_qid and task_family_by_qid[qid] != task_family:
            raise ProjectionError("task_family differs across method or seed")
        task_family_by_qid[qid] = task_family
        costs = row.get("cost_metrics")
        if not isinstance(costs, Mapping) or set(costs) != set(COST_METRICS):
            raise ProjectionError("score row cost metric surface drift")
        for metric in COST_METRICS:
            _finite(costs[metric], f"score.{metric}", unit_interval=False)
        if method in BLOCKED_METHODS:
            if (
                row.get("prediction_status") != "FAILED"
                or row.get("failure_kind") != "PROTOCOL_BLOCKED"
                or row.get("comparison_status") != "PROTOCOL_BLOCKED"
                or row.get("metrics") is not None
                or any(float(costs[metric]) != 0.0 for metric in COST_METRICS)
            ):
                raise ProjectionError("blocked score row drift")
        else:
            expected_comparison = "ELIGIBLE_ACCEPTED" if row.get("prediction_status") == "ACCEPTED" else "ELIGIBLE_FAILURE_IMPUTED"
            metrics = row.get("metrics")
            if (
                row.get("prediction_status") not in {"ACCEPTED", "FAILED"}
                or row.get("comparison_status") != expected_comparison
                or not isinstance(metrics, Mapping) or set(metrics) != set(QUALITY_METRICS)
            ):
                raise ProjectionError("eligible score row drift")
            for metric in QUALITY_METRICS:
                _finite(metrics[metric], f"score.{metric}", unit_interval=True)
    recomputed_method = _normalized_group(scores, ("method_id",))
    summary_method = _summary_groups(summary.get("by_method"), ("method_id",))
    if recomputed_method != summary_method or any(by_method[key[0]] != value for key, value in summary_method.items()):
        raise ProjectionError("by_method summary does not exactly reconcile to score rows")
    recomputed_family = _normalized_group(scores, ("method_id", "task_family"))
    summary_family = _summary_groups(summary.get("by_method_and_task_family"), ("method_id", "task_family"))
    if recomputed_family != summary_family:
        raise ProjectionError("task-family summary does not exactly reconcile to score rows")
    return dict(summary), inventory_sha256


def project_summary(
    summary: Mapping[str, Any],
    template_rows: Sequence[Mapping[str, str]],
    *,
    run_id: str,
    evidence_archive_sha256: str,
) -> list[dict[str, str]]:
    if not isinstance(run_id, str) or not run_id.strip():
        raise ProjectionError("run_id must be nonempty")
    if not isinstance(evidence_archive_sha256, str) or len(evidence_archive_sha256) != 64:
        raise ProjectionError("evidence archive SHA-256 is invalid")
    try:
        int(evidence_archive_sha256, 16)
    except ValueError as exc:
        raise ProjectionError("evidence archive SHA-256 is invalid") from exc
    if [row.get("method_id") for row in template_rows] != list(METHOD_ORDER) + [AGENTENHANCE_METHOD]:
        raise ProjectionError("template row order drift")
    by_method = validate_summary(summary)
    output = deepcopy(list(template_rows))
    for row in output:
        method_id = row["method_id"]
        if method_id == AGENTENHANCE_METHOD:
            continue
        aggregate = by_method[method_id]
        row["accepted_rows"] = str(aggregate["accepted_rows"])
        row["failed_rows"] = str(aggregate["failed_rows"])
        row["run_id"] = run_id
        row["evidence_archive_sha256"] = evidence_archive_sha256
        if method_id in BLOCKED_METHODS:
            continue
        row["comparison_status"] = "ACCEPTED_LOCAL_MATCHED"
        metrics = aggregate["metrics"]
        costs = aggregate["cost_metrics"]
        for table_field, summary_field in TABLE_METRIC_MAP.items():
            source = costs if summary_field in COST_METRICS else metrics
            row[table_field] = _render(float(source[summary_field]))
    return output


def write_projection(
    output_root: Path,
    *,
    fields: Sequence[str],
    rows: Sequence[Mapping[str, str]],
    template_sha256: str,
    evaluation_inventory_sha256: str,
    evidence_archive_sha256: str,
) -> dict[str, Any]:
    if not output_root.is_absolute() or output_root.is_symlink() or output_root.exists():
        raise ProjectionError("output root must be a fresh absolute non-symlink path")
    for digest in (template_sha256, evaluation_inventory_sha256, evidence_archive_sha256):
        if not isinstance(digest, str) or len(digest) != 64:
            raise ProjectionError("projection evidence digest is invalid")
    output_root.mkdir()
    table = output_root / "causal-locomo-main-table.csv"
    with table.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "schema_version": "agentenhance.causal_locomo_main_table_projection.v1",
        "status": "TERMINAL_ACCEPTED",
        "methods": 8,
        "locally_admitted_baseline_methods": 5,
        "protocol_blocked_methods": 2,
        "agentenhance_rows_admitted": 0,
        "metrics_per_eligible_method": len(TABLE_METRIC_MAP),
        "populated_local_metric_cells": len(ELIGIBLE_METHODS) * len(TABLE_METRIC_MAP),
        "official_values_used": False,
        "source_reported_results_read": False,
        "superiority_claim_emitted": False,
        "template_sha256": template_sha256,
        "evaluation_inventory_sha256": evaluation_inventory_sha256,
        "evidence_archive_sha256": evidence_archive_sha256,
        "table_sha256": _sha256_file(table),
    }
    manifest_path = output_root / "projection-manifest.json"
    manifest_path.write_bytes(_canonical_bytes(manifest))
    inventory = "".join(
        f"{_sha256_file(path)}  {path.name}\n" for path in sorted((manifest_path, table), key=lambda item: item.name)
    )
    (output_root / "SHA256SUMS").write_text(inventory, encoding="utf-8")
    (output_root / "TERMINAL_ACCEPTED").touch(exist_ok=False)
    return manifest
