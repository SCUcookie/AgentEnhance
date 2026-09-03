#!/usr/bin/env python3
"""Select a WorldMemArena development-smoke sample by a frozen cost-only rule.

The script mirrors the benchmark loader's sorted JSON-path order. It never
reads answer text and never uses model outputs or evaluation outcomes.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.dataset_root.resolve()
    small_ids = set(json.loads((root / "small_ids.json").read_text(encoding="utf-8")))
    json_paths = sorted(
        path
        for path in root.rglob("*.json")
        if path.name not in {"small_ids.json", "dataset-manifest.json"}
        and path.parent != root
    )

    rows: list[dict[str, object]] = []
    type_counts: Counter[str] = Counter()
    for path in json_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        sample_id = str(payload["sample_id"])
        if sample_id not in small_ids:
            continue
        sessions = payload.get("sessions") or []
        checkpoints = payload.get("qa_checkpoints") or []
        question_count = 0
        evidence_count = 0
        for checkpoint in checkpoints:
            for question in checkpoint.get("questions") or []:
                question_count += 1
                evidence_count += len(question.get("evidence") or [])
                type_counts[str(question.get("question_type_abbrev") or "UNKNOWN")] += 1
        turn_count = sum(len(session.get("dialogue") or []) for session in sessions)
        attachment_count = sum(
            len(turn.get("attachments") or [])
            for session in sessions
            for turn in session.get("dialogue") or []
        )
        rows.append({
            "sample_index": len(rows) + 1,
            "sample_id": sample_id,
            "relative_json_path": path.relative_to(root).as_posix(),
            "session_count": len(sessions),
            "turn_count": turn_count,
            "attachment_count": attachment_count,
            "question_count": question_count,
            "evidence_count": evidence_count,
        })

    if len(small_ids) != 150 or len(rows) != 150:
        raise SystemExit(f"expected 150 selected samples, got ids={len(small_ids)} rows={len(rows)}")
    row_ids = {str(row["sample_id"]) for row in rows}
    if row_ids != small_ids:
        raise SystemExit("loaded sample IDs do not match small_ids.json")

    selected = min(
        rows,
        key=lambda row: (
            int(row["question_count"]),
            int(row["attachment_count"]),
            int(row["session_count"]),
            str(row["sample_id"]),
        ),
    )
    inventory_bytes = (json.dumps(rows, sort_keys=True, separators=(",", ":")) + "\n").encode()
    report = {
        "schema_version": "agentenhance.wma_development_sample_selection.v1",
        "status": "SELECTED_WITHOUT_MODEL_OUTPUTS",
        "dataset_root": str(root),
        "sample_count": len(rows),
        "selection_rule": [
            "min question_count",
            "then min attachment_count",
            "then min session_count",
            "then lexicographic sample_id",
        ],
        "selection_prohibited_inputs": [
            "answer text",
            "model output",
            "evaluation metric",
            "proposed-method result",
        ],
        "selected": selected,
        "question_type_counts": dict(sorted(type_counts.items())),
        "sample_cost_inventory_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output.resolve()
        if output.exists():
            raise SystemExit(f"refusing existing output: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
