#!/usr/bin/env python3
"""Validate the frozen Wave1 failure-history archive contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons/wma-r1-wave1-failure-history-archive-prefreeze.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_AWAITING_RECOVERY2_TERMINAL_QUIESCENCE":
        raise SystemExit("failure-history archive contract status mismatch")
    implementation = ROOT / contract["implementation"]["path"]
    if sha256_file(implementation) != contract["implementation"]["sha256"]:
        raise SystemExit("failure-history archiver identity mismatch")
    sources = contract["sources"]
    if len(sources) != 5:
        raise SystemExit("failure-history source cardinality mismatch")
    totals = contract["frozen_source_totals"]
    if totals["roots"] != len(sources):
        raise SystemExit("failure-history root total mismatch")
    if totals["regular_files"] != sum(row["regular_files_at_freeze"] for row in sources.values()):
        raise SystemExit("failure-history file total mismatch")
    if totals["bytes"] != sum(row["bytes_at_freeze"] for row in sources.values()):
        raise SystemExit("failure-history byte total mismatch")
    if totals["symlinks"] != 0 or totals["storage_ceiling_bytes"] != 2 * 1024**3:
        raise SystemExit("failure-history source safety ceiling mismatch")
    output = contract["output"]
    if not output["root"].startswith("/data2/") or output["must_be_fresh"] is not True:
        raise SystemExit("failure-history output is not a fresh data2 root")
    cleanup = contract["retention_and_cleanup"]
    if any(
        cleanup[field] is not False
        for field in (
            "source_deletion_authorized",
            "archive_deletion_authorized",
            "model_deletion_authorized",
        )
    ):
        raise SystemExit("failure-history contract authorizes deletion")
    source = implementation.read_text(encoding="utf-8")
    required_controls = (
        "tree_sha256",
        "SCHEDULER_EXECUTION_WITH_REJECTIONS",
        "TERMINAL_REJECTED",
        "TERMINAL_ACCEPTED",
        "source_deletion_authorized",
        "MAX_SOURCE_BYTES",
    )
    if not all(control in source for control in required_controls):
        raise SystemExit("failure-history archiver omits a frozen control")
    print(
        json.dumps(
            {
                "status": "PASS",
                "source_roots": len(sources),
                "source_files": totals["regular_files"],
                "source_bytes": totals["bytes"],
                "main_result_rows": 0,
                "deletion_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
