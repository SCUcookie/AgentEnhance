#!/usr/bin/env python3
"""Cross-track gate in front of the frozen two-phase model cleanup controller."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import model_cleanup_controller as base


GLOBAL_COMPLETION_RECORD = Path(
    "/data1/2026/ldh/AgentEnhance/runs/"
    "baseline-cross-track-completion-20260904-v1/cross-track-completion.json"
)
GLOBAL_COMPLETION_CONTRACT = {
    "path": "comparisons/post-wma-cross-track-completion-prefreeze.v1.json",
    "sha256": "f32a8803fc1448e9e6adbaf7a9ba6747dce47b80cde9dcd30eb75007db7ef1f4",
}
WMA_TABLE_SPEC = {
    "path": "comparisons/wma-main-table-spec.v4.json",
    "sha256": "f3a233b6e62419fa054557e18a326d7b2ba59210184bf782556dd1920f8c4937",
}

EXPECTED_METHODS = {
    "wma-lifecycle-matched-v1": {
        "wma-mmfu-single",
        "wma-simplemem",
        "wma-m2a",
        "wma-vilomem",
        "wma-dummy",
        "wma-base-model",
        "wma-fumemory",
        "wma-stmemory",
        "wma-ltmemory",
        "wma-gamemory",
        "wma-mgmemory",
        "wma-rfmemory",
        "wma-mmmemory",
        "wma-mmfumemory",
        "wma-ngmemory",
        "wma-augustus",
        "wma-universalrag",
        "wma-a-mem",
        "wma-omni-simplemem",
        "wma-mirix",
        "wma-qwen3-vl-embedding-8b",
        "wma-memoryos",
        "wma-memgas",
        "wma-memory-r1",
        "wma-apex-mem",
        "wma-lightmem",
        "wma-hindsight",
        "wma-structmem",
        "wma-hela-mem",
    },
    "memgallery-static-matched-v1": {
        "a-mem",
        "memoryos",
        "universalrag",
        "ngm",
        "augustus",
        "m2a",
        "v-mem",
        "no-memory",
        "full-memory-text",
        "full-memory-mm",
        "fifo-recent",
        "bm25",
        "naive-rag",
        "hybrid-rag",
    },
    "causal-locomo-safety-v1": {
        "cmi-no-memory",
        "cmi-full-history",
        "cmi-vector-memory",
        "cmi-summary-memory",
        "cmi-reflection-memory",
        "cmi-graph-memory",
        "cmi",
    },
}


def validate_track_archive(entry: dict) -> Path:
    return base.validate_terminal_root(entry, "cross-track accepted evidence archive")


def validate_global_completion(path: Path = GLOBAL_COMPLETION_RECORD) -> list[Path]:
    path = path.resolve()
    root = path.parent
    if path.name != "cross-track-completion.json":
        raise RuntimeError("cross-track completion record name drift")
    if not path.is_file() or not (root / "TERMINAL_ACCEPTED").is_file():
        raise RuntimeError("cross-track completion is not terminal-accepted")
    if (root / "TERMINAL_REJECTED").exists():
        raise RuntimeError("cross-track completion has a rejection marker")
    inventory = root / "EVIDENCE_SHA256SUMS"
    base.verify_inventory(root, inventory)
    signed_paths = {
        Path(line.split(maxsplit=1)[1].lstrip("*")).resolve()
        for line in inventory.read_text(encoding="utf-8").splitlines()
    }
    if path not in signed_paths:
        raise RuntimeError("cross-track completion record is absent from its inventory")

    payload = base.load_json(path)
    if payload.get("status") != "TERMINAL_ACCEPTED_COMPLETE_SURFACE":
        raise RuntimeError("cross-track completion surface is not accepted")
    if payload.get("global_contract") != GLOBAL_COMPLETION_CONTRACT:
        raise RuntimeError("cross-track completion contract identity drift")
    if payload.get("wma_table_spec") != WMA_TABLE_SPEC:
        raise RuntimeError("WMA table identity drift in cross-track completion")
    if payload.get("official_values_used") is not False:
        raise RuntimeError("cross-track completion used official values")
    if payload.get("all_accepted_and_rejected_evidence_archived") is not True:
        raise RuntimeError("cross-track failures and accepted evidence are not fully archived")
    if payload.get("all_denominators_reconciled") is not True:
        raise RuntimeError("cross-track denominators are not reconciled")

    tracks = payload.get("tracks")
    if not isinstance(tracks, list) or len(tracks) != len(EXPECTED_METHODS):
        raise RuntimeError("cross-track completion track cardinality drift")
    by_id = {row.get("track_id"): row for row in tracks}
    if set(by_id) != set(EXPECTED_METHODS) or len(by_id) != len(tracks):
        raise RuntimeError("cross-track completion track identities drift")
    retained = [root]
    for track_id, expected in EXPECTED_METHODS.items():
        row = by_id[track_id]
        if row.get("status") != "TERMINAL_ACCEPTED_COMPLETE_SURFACE":
            raise RuntimeError(f"track is not complete: {track_id}")
        registered = row.get("registered_methods")
        accepted = row.get("accepted_methods")
        terminal = row.get("terminal_blocked_or_failed_methods")
        if not all(isinstance(value, list) for value in (registered, accepted, terminal)):
            raise RuntimeError(f"track method partitions must be lists: {track_id}")
        if len(registered) != len(set(registered)) or set(registered) != expected:
            raise RuntimeError(f"registered method surface drift: {track_id}")
        if set(accepted) & set(terminal) or set(accepted) | set(terminal) != expected:
            raise RuntimeError(f"accepted/terminal partition is incomplete: {track_id}")
        if row.get("official_values_used") is not False:
            raise RuntimeError(f"track used official values: {track_id}")
        if row.get("denominator_reconciled") is not True:
            raise RuntimeError(f"track denominator is incomplete: {track_id}")
        retained.append(validate_track_archive(row["archive"]))
    return retained


def _guarded(operation, *args):
    before = validate_global_completion(GLOBAL_COMPLETION_RECORD)
    result = operation(*args)
    after = validate_global_completion(GLOBAL_COMPLETION_RECORD)
    if set(before) != set(after):
        raise RuntimeError("cross-track retained-evidence roots changed during cleanup")
    return result


def preflight(record: Path) -> int:
    return _guarded(base.preflight, record)


def quarantine(record: Path, output: Path) -> int:
    return _guarded(base.quarantine, record, output)


def delete_quarantine(record: Path, output: Path) -> int:
    return _guarded(base.delete_quarantine, record, output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("preflight", "quarantine", "delete"))
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--output-record", type=Path)
    args = parser.parse_args()
    if args.phase == "preflight":
        if args.output_record is not None:
            raise SystemExit("preflight does not write an output record")
        return preflight(args.record.resolve())
    if args.output_record is None:
        raise SystemExit("quarantine and delete require --output-record")
    output = args.output_record.resolve()
    if args.phase == "quarantine":
        return quarantine(args.record.resolve(), output)
    return delete_quarantine(args.record.resolve(), output)


if __name__ == "__main__":
    raise SystemExit(main())
