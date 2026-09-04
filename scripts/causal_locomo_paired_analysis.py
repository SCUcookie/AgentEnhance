#!/usr/bin/env python3
"""Result-free paired statistics for future local Causal-LoCoMo scores."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.project_causal_locomo_main_table import (
    BLOCKED_METHODS,
    COST_METRICS,
    QUALITY_METRICS,
    load_evaluation_root,
)


METHOD_ORDER = (
    "cmi-no-memory",
    "cmi-full-history",
    "cmi-vector-memory",
    "cmi-summary-memory",
    "cmi-graph-memory",
)
COMPARISONS = tuple(itertools.combinations(METHOD_ORDER, 2))
LOWER_IS_BETTER = frozenset({
    "poisoned_memory_adoption_rate",
    "false_positive_memory_acceptance_rate",
    "false_negative_memory_rejection_rate",
    "harmful_instruction_following_rate",
    "endpoint_calls",
    "failed_endpoint_calls",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "wall_seconds",
    "selected_memory_count",
    "retrieved_memory_count",
})
PRIMARY_METRIC = "task_score"
BOOTSTRAP_REPLICATES = 10_000
PERMUTATION_REPLICATES = 100_000
RANDOMIZATION_NAMESPACE = "agentenhance-causal-locomo-paired-20260904-v1"
PAIRWISE_FIELDS = (
    "method_a", "method_b", "metric", "direction", "analysis_unit", "n_qids",
    "n_seed_qid_pairs", "mean_a", "mean_b", "mean_difference_a_minus_b",
    "median_qid_difference", "ci95_low", "ci95_high", "wins_a", "ties",
    "losses_a", "p_unadjusted", "p_adjusted", "adjustment", "outcome",
)


class PairedAnalysisError(RuntimeError):
    """The score surface or prospective statistical rule was violated."""


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _seed(*parts: str) -> int:
    payload = "|".join((RANDOMIZATION_NAMESPACE, *parts)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise PairedAnalysisError("cannot take a quantile of an empty sample")
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    fraction = position - lower
    return float(sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction)


def paired_statistics(
    values_a: Sequence[float],
    values_b: Sequence[float],
    *,
    direction: str,
    randomization_key: str,
    bootstrap_replicates: int,
    permutation_replicates: int,
) -> dict[str, Any]:
    """Cluster-level paired statistics; public execution freezes 87 qid means."""
    if direction not in {"higher", "lower"}:
        raise PairedAnalysisError("direction must be higher or lower")
    if len(values_a) != len(values_b) or not values_a:
        raise PairedAnalysisError("paired vectors must be nonempty and equally sized")
    if bootstrap_replicates <= 0 or permutation_replicates < 0:
        raise PairedAnalysisError("replicate counts are invalid")
    a = [float(value) for value in values_a]
    b = [float(value) for value in values_b]
    if not all(math.isfinite(value) for value in (*a, *b)):
        raise PairedAnalysisError("paired vectors contain non-finite values")
    differences = [left - right for left, right in zip(a, b)]
    n = len(differences)
    mean_difference = sum(differences) / n
    bootstrap_rng = random.Random(_seed(randomization_key, "cluster-bootstrap"))
    bootstrap = sorted(
        sum(differences[bootstrap_rng.randrange(n)] for _ in range(n)) / n
        for _ in range(bootstrap_replicates)
    )
    ci_low = _quantile(bootstrap, 0.025)
    ci_high = _quantile(bootstrap, 0.975)
    if permutation_replicates:
        permutation_rng = random.Random(_seed(randomization_key, "paired-sign-flip"))
        extreme = 0
        observed = abs(mean_difference)
        for _ in range(permutation_replicates):
            permuted = sum(value if permutation_rng.getrandbits(1) else -value for value in differences) / n
            extreme += abs(permuted) >= observed - 1e-15
        p_value: float | None = (extreme + 1.0) / (permutation_replicates + 1.0)
    else:
        p_value = None
    tolerance = 1e-12
    signed = differences if direction == "higher" else [-value for value in differences]
    wins = sum(value > tolerance for value in signed)
    losses = sum(value < -tolerance for value in signed)
    ties = n - wins - losses
    oriented_low = ci_low if direction == "higher" else -ci_high
    oriented_high = ci_high if direction == "higher" else -ci_low
    outcome = "IMPROVEMENT" if oriented_low > 0 else "DEGRADATION" if oriented_high < 0 else "INCONCLUSIVE"
    return {
        "mean_a": sum(a) / n,
        "mean_b": sum(b) / n,
        "mean_difference_a_minus_b": mean_difference,
        "median_qid_difference": statistics.median(differences),
        "ci95_low": ci_low,
        "ci95_high": ci_high,
        "wins_a": wins,
        "ties": ties,
        "losses_a": losses,
        "p_unadjusted": p_value,
        "outcome": outcome,
    }


def holm_adjust(p_values: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for rank, (key, value) in enumerate(ordered):
        running = max(running, min(1.0, (total - rank) * value))
        adjusted[key] = running
    return adjusted


def benjamini_hochberg_adjust(p_values: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]), reverse=True)
    adjusted: dict[str, float] = {}
    running = 1.0
    total = len(ordered)
    for reverse_rank, (key, value) in enumerate(ordered, start=1):
        forward_rank = total - reverse_rank + 1
        running = min(running, min(1.0, value * total / forward_rank))
        adjusted[key] = running
    return adjusted


def _qid_seed_values(score_rows: Sequence[Mapping[str, Any]]) -> tuple[list[str], dict[tuple[str, str, str], float]]:
    qids: list[str] = []
    values: dict[tuple[str, str, str], float] = {}
    for row in score_rows:
        method = row.get("method_id")
        if method in BLOCKED_METHODS:
            continue
        if method not in METHOD_ORDER:
            raise PairedAnalysisError(f"unexpected eligible method: {method}")
        qid = row.get("example_id")
        seed = row.get("seed")
        if not isinstance(qid, str) or seed not in {0, 1, 2}:
            raise PairedAnalysisError("score identity drift")
        if seed == 0 and method == METHOD_ORDER[0]:
            qids.append(qid)
        metrics = row.get("metrics")
        costs = row.get("cost_metrics")
        if not isinstance(metrics, Mapping) or not isinstance(costs, Mapping):
            raise PairedAnalysisError("eligible score row lacks metrics")
        for metric in QUALITY_METRICS:
            values[(method, qid, f"{seed}:{metric}")] = float(metrics[metric])
        for metric in COST_METRICS:
            values[(method, qid, f"{seed}:{metric}")] = float(costs[metric])
    if len(qids) != 87 or len(qids) != len(set(qids)):
        raise PairedAnalysisError("qid analysis surface drift")
    expected = len(METHOD_ORDER) * len(qids) * 3 * (len(QUALITY_METRICS) + len(COST_METRICS))
    if len(values) != expected:
        raise PairedAnalysisError("paired value surface is incomplete")
    return qids, values


def _qid_means(
    values: Mapping[tuple[str, str, str], float],
    qids: Sequence[str],
    method: str,
    metric: str,
) -> list[float]:
    return [sum(values[(method, qid, f"{seed}:{metric}")] for seed in (0, 1, 2)) / 3.0 for qid in qids]


def analyze_score_rows(
    score_rows: Sequence[Mapping[str, Any]],
    *,
    bootstrap_replicates: int = BOOTSTRAP_REPLICATES,
    permutation_replicates: int = PERMUTATION_REPLICATES,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    qids, values = _qid_seed_values(score_rows)
    quality_rows: list[dict[str, Any]] = []
    cost_rows: list[dict[str, Any]] = []
    for metric in (*QUALITY_METRICS, *COST_METRICS):
        direction = "lower" if metric in LOWER_IS_BETTER else "higher"
        for method_a, method_b in COMPARISONS:
            stats = paired_statistics(
                _qid_means(values, qids, method_a, metric),
                _qid_means(values, qids, method_b, metric),
                direction=direction,
                randomization_key=f"{method_a}|{method_b}|{metric}",
                bootstrap_replicates=bootstrap_replicates,
                permutation_replicates=permutation_replicates if metric in QUALITY_METRICS else 0,
            )
            row = {
                "method_a": method_a,
                "method_b": method_b,
                "metric": metric,
                "direction": direction,
                "analysis_unit": "qid_mean_over_seeds",
                "n_qids": len(qids),
                "n_seed_qid_pairs": len(qids) * 3,
                **stats,
                "p_adjusted": None,
                "adjustment": "none_descriptive" if metric in COST_METRICS else "pending",
            }
            (quality_rows if metric in QUALITY_METRICS else cost_rows).append(row)
    for metric in QUALITY_METRICS:
        family = [row for row in quality_rows if row["metric"] == metric]
        p_values = {f"{row['method_a']}|{row['method_b']}": row["p_unadjusted"] for row in family}
        adjusted = holm_adjust(p_values) if metric == PRIMARY_METRIC else benjamini_hochberg_adjust(p_values)
        adjustment = "holm_within_primary_task_score_10" if metric == PRIMARY_METRIC else f"bh_within_{metric}_10"
        for row in family:
            key = f"{row['method_a']}|{row['method_b']}"
            row["p_adjusted"] = adjusted[key]
            row["adjustment"] = adjustment
    return quality_rows, cost_rows


def analyze_evaluation_root(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Production entry: full audit plus frozen 10k bootstrap/100k sign flips."""
    _, inventory_sha256 = load_evaluation_root(root)
    try:
        score_rows = [json.loads(line) for line in (root / "scores.jsonl").read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PairedAnalysisError(f"cannot reload audited score rows: {exc}") from exc
    quality, cost = analyze_score_rows(
        score_rows,
        bootstrap_replicates=BOOTSTRAP_REPLICATES,
        permutation_replicates=PERMUTATION_REPLICATES,
    )
    return quality, cost, inventory_sha256


def write_analysis(
    output_root: Path,
    *,
    quality_rows: Sequence[Mapping[str, Any]],
    cost_rows: Sequence[Mapping[str, Any]],
    evaluation_inventory_sha256: str,
) -> dict[str, Any]:
    if not output_root.is_absolute() or output_root.is_symlink() or output_root.exists():
        raise PairedAnalysisError("output root must be a fresh absolute non-symlink path")
    if len(quality_rows) != len(QUALITY_METRICS) * len(COMPARISONS) or len(cost_rows) != len(COST_METRICS) * len(COMPARISONS):
        raise PairedAnalysisError("pairwise output cardinality drift")
    if len(evaluation_inventory_sha256) != 64:
        raise PairedAnalysisError("evaluation inventory SHA-256 is invalid")
    for rows, metrics, inferential in (
        (quality_rows, QUALITY_METRICS, True), (cost_rows, COST_METRICS, False),
    ):
        expected = {(method_a, method_b, metric) for metric in metrics for method_a, method_b in COMPARISONS}
        observed: set[tuple[str, str, str]] = set()
        for row in rows:
            key = (row.get("method_a"), row.get("method_b"), row.get("metric"))
            if key not in expected or key in observed:
                raise PairedAnalysisError("pairwise output identity drift")
            observed.add(key)
            metric = key[2]
            expected_direction = "lower" if metric in LOWER_IS_BETTER else "higher"
            if (
                row.get("direction") != expected_direction
                or row.get("analysis_unit") != "qid_mean_over_seeds"
                or row.get("n_qids") != 87
                or row.get("n_seed_qid_pairs") != 261
                or row.get("wins_a", -1) + row.get("ties", -1) + row.get("losses_a", -1) != 87
                or row.get("outcome") not in {"IMPROVEMENT", "DEGRADATION", "INCONCLUSIVE"}
            ):
                raise PairedAnalysisError("pairwise output semantics drift")
            for field in (
                "mean_a", "mean_b", "mean_difference_a_minus_b", "median_qid_difference",
                "ci95_low", "ci95_high",
            ):
                value = row.get(field)
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                    raise PairedAnalysisError("pairwise output contains a non-finite statistic")
            if row["ci95_low"] > row["ci95_high"]:
                raise PairedAnalysisError("pairwise confidence interval is reversed")
            if inferential:
                if (
                    not isinstance(row.get("p_unadjusted"), (int, float))
                    or not isinstance(row.get("p_adjusted"), (int, float))
                    or not 0 <= row["p_unadjusted"] <= row["p_adjusted"] <= 1
                    or row.get("adjustment") == "pending"
                ):
                    raise PairedAnalysisError("pairwise inferential adjustment drift")
            elif (
                row.get("p_unadjusted") is not None
                or row.get("p_adjusted") is not None
                or row.get("adjustment") != "none_descriptive"
            ):
                raise PairedAnalysisError("cost rows must remain descriptive")
        if observed != expected:
            raise PairedAnalysisError("pairwise output surface is incomplete")
    output_root.mkdir()
    outputs = []
    for name, rows in (("pairwise-quality.csv", quality_rows), ("pairwise-cost.csv", cost_rows)):
        path = output_root / name
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(PAIRWISE_FIELDS), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        outputs.append(path)
    manifest = {
        "schema_version": "agentenhance.causal_locomo_paired_analysis.v1",
        "status": "TERMINAL_ACCEPTED",
        "analysis_unit": "87 qids after averaging the three paired seeds within qid",
        "eligible_methods": list(METHOD_ORDER),
        "method_pairs": len(COMPARISONS),
        "quality_metrics": len(QUALITY_METRICS),
        "cost_metrics": len(COST_METRICS),
        "quality_rows": len(quality_rows),
        "cost_rows": len(cost_rows),
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "permutation_replicates": PERMUTATION_REPLICATES,
        "primary_adjustment": "Holm within ten task_score contrasts",
        "secondary_adjustment": "Benjamini-Hochberg separately within each secondary quality metric",
        "cost_inference": "descriptive paired effects and cluster-bootstrap interval only",
        "official_values_used": False,
        "agentenhance_included": False,
        "sota_claim_emitted": False,
        "evaluation_inventory_sha256": evaluation_inventory_sha256,
    }
    manifest_path = output_root / "analysis-manifest.json"
    manifest_path.write_bytes(_canonical_bytes(manifest))
    outputs.append(manifest_path)
    inventory = "".join(f"{_sha256_file(path)}  {path.name}\n" for path in sorted(outputs, key=lambda item: item.name))
    (output_root / "SHA256SUMS").write_text(inventory, encoding="utf-8")
    (output_root / "TERMINAL_ACCEPTED").touch(exist_ok=False)
    return manifest
