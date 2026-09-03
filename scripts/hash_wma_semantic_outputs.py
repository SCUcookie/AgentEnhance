#!/usr/bin/env python3
"""Hash WMA semantic outputs while excluding runtime and generated UUID fields."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


DROP_KEYS = {
    "answer_seconds",
    "retrieval_seconds",
    "raw_backend_id",
    "memory_id",
    "cited_memories",
}


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: clean(child)
            for key, child in sorted(value.items())
            if key not in DROP_KEYS
        }
    if isinstance(value, list):
        return [clean(child) for child in value]
    return value


def digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("unit_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.unit_root.resolve()
    if not (root / "TERMINAL_ACCEPTED").is_file():
        raise SystemExit(f"unit is not terminal-accepted: {root}")
    aggregate = json.loads((root / "output/aggregate_metrics.json").read_text(encoding="utf-8"))
    aggregate.pop("runtime", None)
    aggregate.pop("timing", None)
    semantic = {
        "aggregate_semantic_sha256": digest(clean(aggregate)),
        "session_semantic_sha256": digest(clean(load_jsonl(root / "output/session_records.jsonl"))),
        "qa_semantic_sha256": digest(clean(load_jsonl(root / "output/qa_records.jsonl"))),
    }
    report = {
        "schema_version": "agentenhance.wma_semantic_digest.v1",
        "unit_root": str(root),
        **semantic,
    }
    report["combined_semantic_sha256"] = digest(semantic)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        if args.output.exists():
            raise SystemExit(f"refusing existing output: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
