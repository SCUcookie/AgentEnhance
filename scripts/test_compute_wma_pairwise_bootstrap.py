#!/usr/bin/env python3
"""Synthetic checks for paired WMA cluster bootstrap mechanics."""

from __future__ import annotations

import math

from compute_wma_pairwise_bootstrap import paired_bootstrap
from wma_pairwise_sufficient_stats import PAIRED_METRIC_KEYS, RatioStat


def make_stats(offset: float) -> dict[int, dict[str, dict[str, RatioStat]]]:
    output: dict[int, dict[str, dict[str, RatioStat]]] = {}
    for seed in (0, 1, 2):
        output[seed] = {}
        for sample in range(7):
            output[seed][str(sample)] = {
                metric: RatioStat(
                    numerator=float((metric_index + 1) * (sample + 1) + seed) + offset,
                    denominator=float((metric_index % 5) + sample + 3),
                )
                for metric_index, metric in enumerate(PAIRED_METRIC_KEYS)
            }
    return output


def main() -> int:
    stats_a = make_stats(2.0)
    stats_b = make_stats(0.0)
    first = paired_bootstrap(
        stats_a, stats_b, [str(index) for index in range(7)], resamples=500, bootstrap_seed=77
    )
    second = paired_bootstrap(
        stats_a, stats_b, [str(index) for index in range(7)], resamples=500, bootstrap_seed=77
    )
    if first != second:
        raise SystemExit("paired bootstrap is not deterministic")
    for metric, row in first.items():
        if not row["point_difference"] > 0:
            raise SystemExit(f"expected positive A-B point difference: {metric}")
        if not row["ci95_low"] <= row["point_difference"] <= row["ci95_high"]:
            raise SystemExit(f"point estimate outside interval: {metric}")
        expected_seed_differences = []
        for seed in (0, 1, 2):
            a_num = sum(stats_a[seed][str(i)][metric].numerator for i in range(7))
            b_num = sum(stats_b[seed][str(i)][metric].numerator for i in range(7))
            denominator = sum(stats_a[seed][str(i)][metric].denominator for i in range(7))
            expected_seed_differences.append((a_num - b_num) / denominator)
        expected = sum(expected_seed_differences) / 3
        if not math.isclose(row["point_difference"], expected, rel_tol=1e-12, abs_tol=1e-12):
            raise SystemExit(f"wrong three-seed point estimate: {metric}")
    identical = paired_bootstrap(
        stats_a, stats_a, [str(index) for index in range(7)], resamples=200, bootstrap_seed=88
    )
    if any(
        not math.isclose(value, 0.0, abs_tol=1e-15)
        for row in identical.values()
        for value in row.values()
    ):
        raise SystemExit("identical paired inputs did not produce an exact zero difference")
    print(f"synthetic-pairwise-bootstrap=PASS metrics={len(first)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
