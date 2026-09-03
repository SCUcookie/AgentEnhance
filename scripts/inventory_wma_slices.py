#!/usr/bin/env python3
"""Inventory pre-result WorldMemArena slice denominators without reading answers."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    root = args.dataset_root.resolve()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing existing output: {output}")
    sample_ids = set(json.loads((root / "small_ids.json").read_text(encoding="utf-8")))
    sample_counts: Counter[str] = Counter()
    question_counts: Counter[str] = Counter()
    difficulty_counts: Counter[str] = Counter()
    question_type_counts: Counter[str] = Counter()
    evidence_modality_counts: Counter[str] = Counter()
    scope_sample_counts: Counter[str] = Counter()
    scope_question_counts: Counter[str] = Counter()
    family_sample_counts: Counter[str] = Counter()
    family_question_counts: Counter[str] = Counter()

    selected_ids: set[str] = set()
    for path in sorted(root.rglob("*.json")):
        if path.name in {"small_ids.json", "dataset-manifest.json"} or path.parent == root:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        sample_id = str(payload["sample_id"])
        if sample_id not in sample_ids:
            continue
        selected_ids.add(sample_id)
        parts = path.relative_to(root).parts
        subcategory = "/".join(parts[:-1])
        scope = parts[0]
        family = "/".join(parts[:2]) if len(parts) > 2 else scope
        sample_counts[subcategory] += 1
        scope_sample_counts[scope] += 1
        family_sample_counts[family] += 1

        for checkpoint in payload.get("qa_checkpoints") or []:
            for question in checkpoint.get("questions") or []:
                question_counts[subcategory] += 1
                scope_question_counts[scope] += 1
                family_question_counts[family] += 1
                difficulty_counts[str(question.get("difficulty") or "UNKNOWN")] += 1
                question_type_counts[str(question.get("question_type_abbrev") or "UNKNOWN")] += 1
                modalities: set[str] = set()
                for evidence in question.get("evidence") or []:
                    if evidence.get("memory_id"):
                        modalities.add("memory")
                    if evidence.get("image_id"):
                        modalities.add("image")
                evidence_modality_counts["+".join(sorted(modalities)) or "none"] += 1

    if selected_ids != sample_ids or len(sample_ids) != 150:
        raise SystemExit(
            f"sample ID mismatch: selected={len(selected_ids)} expected={len(sample_ids)}"
        )
    total_questions = sum(question_type_counts.values())
    for counter in (
        question_counts,
        difficulty_counts,
        evidence_modality_counts,
        scope_question_counts,
        family_question_counts,
    ):
        if sum(counter.values()) != total_questions:
            raise SystemExit("slice denominator mismatch")

    subcategories = {
        key: {"samples": sample_counts[key], "questions": question_counts[key]}
        for key in sorted(sample_counts)
    }
    denominator_payload = {
        "scope_samples": dict(sorted(scope_sample_counts.items())),
        "scope_questions": dict(sorted(scope_question_counts.items())),
        "family_samples": dict(sorted(family_sample_counts.items())),
        "family_questions": dict(sorted(family_question_counts.items())),
        "difficulty_questions": dict(sorted(difficulty_counts.items())),
        "question_type_questions": dict(sorted(question_type_counts.items())),
        "evidence_modality_questions": dict(sorted(evidence_modality_counts.items())),
        "subcategories": subcategories,
    }
    denominator_bytes = (
        json.dumps(denominator_payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    report = {
        "schema_version": "agentenhance.wma_slice_inventory.v1",
        "status": "FROZEN_BEFORE_NUMERIC_RESULTS",
        "sample_count": len(sample_ids),
        "question_count": total_questions,
        "prohibited_inputs": ["answer text", "model output", "evaluation result"],
        "slice_denominator_sha256": hashlib.sha256(denominator_bytes).hexdigest(),
        **denominator_payload,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "samples": report["sample_count"],
        "questions": report["question_count"],
        "subcategories": len(subcategories),
        "slice_denominator_sha256": report["slice_denominator_sha256"],
        "output": str(output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
