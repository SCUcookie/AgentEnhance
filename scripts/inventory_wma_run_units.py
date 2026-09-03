#!/usr/bin/env python3
"""Freeze the exact WorldMemArena small-split sample order and denominators."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("output_csv", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()

    root = args.dataset_root.resolve()
    small_ids_path = root / "small_ids.json"
    manifest_path = root / "dataset-manifest.json"
    small_ids = set(json.loads(small_ids_path.read_text(encoding="utf-8")))
    rows: list[dict[str, object]] = []

    paths = sorted(
        path
        for path in root.rglob("*.json")
        if path.name != "small_ids.json" and path.parent != root
    )
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        sample_id = str(payload.get("sample_id") or "")
        if sample_id not in small_ids:
            continue
        sessions = payload.get("sessions") or []
        qa_checkpoints = payload.get("qa_checkpoints") or []
        turns = sum(len(session.get("dialogue") or []) for session in sessions)
        attachments = sum(
            len(turn.get("attachments") or [])
            for session in sessions
            for turn in session.get("dialogue") or []
        )
        questions = sum(len(checkpoint.get("questions") or []) for checkpoint in qa_checkpoints)
        rows.append(
            {
                "sample_index": len(rows) + 1,
                "sample_id": sample_id,
                "relative_json_path": path.relative_to(root).as_posix(),
                "sessions": len(sessions),
                "turns": turns,
                "attachments": attachments,
                "qa": questions,
                "source_json_sha256": sha256_file(path),
            }
        )

    if len(rows) != 150:
        raise SystemExit(f"expected 150 samples, found {len(rows)}")
    if len({str(row["sample_id"]) for row in rows}) != len(rows):
        raise SystemExit("duplicate sample_id")

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    if args.output_csv.exists() or args.output_json.exists():
        raise SystemExit("refusing to overwrite an existing inventory")
    fields = list(rows[0])
    with args.output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "schema_version": "agentenhance.wma_run_unit_inventory.v1",
        "status": "FROZEN_FROM_METADATA_ONLY",
        "dataset_root_name": root.name,
        "dataset_manifest_sha256": sha256_file(manifest_path),
        "small_ids_sha256": sha256_file(small_ids_path),
        "sample_order_rule": "sorted recursive JSON paths, then small_ids membership; matches pinned WMA loader",
        "n_samples": len(rows),
        "n_sessions": sum(int(row["sessions"]) for row in rows),
        "n_turns": sum(int(row["turns"]) for row in rows),
        "n_attachments": sum(int(row["attachments"]) for row in rows),
        "n_qa": sum(int(row["qa"]) for row in rows),
        "inventory_csv_sha256": sha256_file(args.output_csv),
    }
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
