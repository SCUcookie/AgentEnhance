#!/usr/bin/env python3
"""Sufficient statistics for paired WorldMemArena sample-cluster inference."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class RatioStat:
    numerator: float
    denominator: float

    @property
    def value(self) -> float:
        return self.numerator / self.denominator if self.denominator else 0.0


PAIRED_METRIC_KEYS = (
    "interference_rejection.score",
    "memory_accuracy_itemwise.avg_correctness",
    "memory_accuracy_itemwise.avg_hallucination",
    "memory_correctness.avg_correctness",
    "memory_correctness.avg_hallucination",
    "memory_correctness.avg_irrelevant",
    "memory_recall.avg_recall",
    "memory_recall.avg_weighted_recall",
    "memory_recall.pooled_weighted_recall",
    "question_answering.answer_matching.avg_bleu1",
    "question_answering.answer_matching.avg_f1",
    "question_answering.correct_ratio",
    "question_answering.hallucination_ratio",
    "question_answering.notmention_when_retrieved_ratio",
    "question_answering.omission_ratio",
    "question_answering.retrieval_coverage.hit_rate",
    "question_answering.retrieval_ranking.ndcg_at.1",
    "question_answering.retrieval_ranking.ndcg_at.10",
    "question_answering.retrieval_ranking.ndcg_at.5",
    "question_answering.retrieval_ranking.recall_at.1",
    "question_answering.retrieval_ranking.recall_at.10",
    "question_answering.retrieval_ranking.recall_at.5",
    "update_handling.score",
)


def _mean_stat(values: Iterable[float]) -> RatioStat:
    rows = list(values)
    return RatioStat(sum(rows), float(len(rows)))


def aggregate_record_stats(
    qa_records: list[dict[str, Any]],
    session_records: list[dict[str, Any]],
) -> dict[str, RatioStat]:
    qa_evals = [row["eval"] for row in qa_records]
    session_evals = [row["eval"] for row in session_records]
    valid_qa = [
        row
        for row in qa_evals
        if row.get("answer_label") in {"Correct", "Hallucination", "Omission"}
    ]

    stats: dict[str, RatioStat] = {}
    for label, key in (
        ("Correct", "question_answering.correct_ratio"),
        ("Hallucination", "question_answering.hallucination_ratio"),
        ("Omission", "question_answering.omission_ratio"),
    ):
        stats[key] = RatioStat(
            float(sum(row.get("answer_label") == label for row in valid_qa)),
            float(len(valid_qa)),
        )
    stats["question_answering.notmention_when_retrieved_ratio"] = RatioStat(
        float(
            sum(
                row.get("answer_label") == "Omission"
                and int(row.get("retrieval_covered_count") or 0) > 0
                for row in valid_qa
            )
        ),
        float(len(valid_qa)),
    )
    stats["question_answering.answer_matching.avg_f1"] = _mean_stat(
        float(row.get("answer_f1") or 0.0) for row in qa_evals
    )
    stats["question_answering.answer_matching.avg_bleu1"] = _mean_stat(
        float(row.get("answer_bleu1") or 0.0) for row in qa_evals
    )
    stats["question_answering.retrieval_coverage.hit_rate"] = _mean_stat(
        float(row.get("retrieval_hit_rate") or 0.0) for row in qa_evals
    )
    for family, source in (
        ("recall_at", "retrieval_recall_at"),
        ("ndcg_at", "retrieval_ndcg_at"),
    ):
        for cutoff in ("1", "5", "10"):
            stats[f"question_answering.retrieval_ranking.{family}.{cutoff}"] = _mean_stat(
                float((row.get(source) or {}).get(cutoff, 0.0) or 0.0)
                for row in qa_evals
            )

    stats["memory_recall.avg_recall"] = _mean_stat(
        float(row["recall"])
        for row in session_evals
        if row.get("recall") is not None
    )
    stats["memory_recall.avg_weighted_recall"] = _mean_stat(
        float(row["weighted_recall"])
        for row in session_evals
        if row.get("weighted_recall") is not None
    )
    stats["memory_recall.pooled_weighted_recall"] = RatioStat(
        sum(float(row.get("weighted_covered_importance") or 0.0) for row in session_evals),
        sum(float(row.get("total_importance") or 0.0) for row in session_evals),
    )
    stats["memory_correctness.avg_correctness"] = _mean_stat(
        float(row["correctness_rate"])
        for row in session_evals
        if row.get("correctness_rate") is not None
    )
    stats["memory_correctness.avg_hallucination"] = _mean_stat(
        float(row.get("num_hallucination") or 0.0)
        / float(row.get("num_memories") or 1.0)
        for row in session_evals
        if int(row.get("num_memories") or 0) > 0
    )
    stats["memory_correctness.avg_irrelevant"] = _mean_stat(
        float(row.get("num_error") or 0.0) / float(row.get("num_memories") or 1.0)
        for row in session_evals
        if int(row.get("num_memories") or 0) > 0
    )

    itemwise = [
        row["memory_accuracy_itemwise"]
        for row in session_evals
        if row.get("memory_accuracy_itemwise")
        and not row["memory_accuracy_itemwise"].get("skipped", False)
    ]
    stats["memory_accuracy_itemwise.avg_correctness"] = _mean_stat(
        float(row.get("itemwise_correctness") or 0.0) for row in itemwise
    )
    stats["memory_accuracy_itemwise.avg_hallucination"] = _mean_stat(
        float(row.get("itemwise_hallucination") or 0.0) for row in itemwise
    )

    stats["update_handling.score"] = RatioStat(
        sum(
            float(row.get("update_num_updated") or 0.0)
            + 0.5 * float(row.get("update_num_both") or 0.0)
            for row in session_evals
        ),
        sum(float(row.get("update_total_items") or 0.0) for row in session_evals),
    )
    stats["interference_rejection.score"] = RatioStat(
        sum(float(row.get("interference_num_rejected") or 0.0) for row in session_evals),
        sum(float(row.get("interference_total_items") or 0.0) for row in session_evals),
    )
    if set(stats) != set(PAIRED_METRIC_KEYS):
        missing = sorted(set(PAIRED_METRIC_KEYS) - set(stats))
        extra = sorted(set(stats) - set(PAIRED_METRIC_KEYS))
        raise RuntimeError(f"paired metric schema mismatch; missing={missing}, extra={extra}")
    return stats


def group_sample_stats(
    qa_records: list[dict[str, Any]],
    session_records: list[dict[str, Any]],
) -> dict[str, dict[str, RatioStat]]:
    qa_by_sample: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sessions_by_sample: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in qa_records:
        qa_by_sample[str(row["sample_id"])].append(row)
    for row in session_records:
        sessions_by_sample[str(row["sample_id"])].append(row)
    sample_ids = set(qa_by_sample) | set(sessions_by_sample)
    return {
        sample_id: aggregate_record_stats(
            qa_by_sample.get(sample_id, []), sessions_by_sample.get(sample_id, [])
        )
        for sample_id in sorted(sample_ids)
    }
