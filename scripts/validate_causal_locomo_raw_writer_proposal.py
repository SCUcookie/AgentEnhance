#!/usr/bin/env python3
"""Validate the result-free Causal-LoCoMo append-only writer proposal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "causal-locomo-raw-writer-proposal.v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    proposal = json.loads(PATH.read_text(encoding="utf-8"))
    if proposal.get("state") != "PROPOSED_SYNTHETIC_ONLY_NOT_FROZEN_NOT_AUTHORIZED":
        raise SystemExit("raw writer proposal state drift")
    for parent in proposal["parents"]:
        if sha256(ROOT / parent["path"]) != parent["sha256"]:
            raise SystemExit(f"raw writer parent drift: {parent['path']}")
    expected_methods = [
        "cmi-no-memory", "cmi-full-history", "cmi-vector-memory",
        "cmi-summary-memory", "cmi-reflection-memory", "cmi-graph-memory", "cmi",
    ]
    ordering = proposal["ordering"]
    if ordering["minor_method_order"] != expected_methods:
        raise SystemExit("raw writer method order drift")
    if (ordering["rows_per_seed"], ordering["rows_across_seeds"]) != (609, 1827):
        raise SystemExit("raw writer denominator drift")
    semantics = proposal["row_semantics"]
    if (semantics["protocol_blocked_rows_per_seed"], semantics["protocol_blocked_rows_total"]) != (174, 522):
        raise SystemExit("blocked-row denominator drift")
    filesystem = proposal["filesystem_contract"]
    if (
        filesystem["fresh_absolute_root"], filesystem["inventory_members"],
        filesystem["automatic_retry"], filesystem["partial_root_reuse"],
    ) != (True, 4, False, False):
        raise SystemExit("raw writer filesystem contract drift")
    observations = proposal["current_observations"]
    if observations["official_values_used"] or any(
        observations[key] != 0 for key in ("real_seed_roots", "real_rows", "scores_observed")
    ):
        raise SystemExit("raw writer proposal contains real result evidence")
    if "authorizes no server root" not in proposal["authorization"]:
        raise SystemExit("raw writer authorization boundary missing")
    print(json.dumps({
        "status": "PASS",
        "proposal_sha256": sha256(PATH),
        "implementation_sha256": sha256(ROOT / proposal["implementation"]),
        "rows_per_seed": ordering["rows_per_seed"],
        "blocked_rows_total": semantics["protocol_blocked_rows_total"],
        "real_rows": observations["real_rows"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

