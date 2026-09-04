#!/usr/bin/env python3
"""Validate the result-free five-method Causal-LoCoMo overlay proposal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "causal-locomo-five-method-overlay-proposal.v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    proposal = json.loads(PATH.read_text(encoding="utf-8"))
    if proposal.get("state") != "PROPOSED_RESULT_FREE_NOT_FROZEN_NOT_AUTHORIZED":
        raise SystemExit("overlay proposal state drift")
    parent = proposal["parent_contract"]
    if sha256(ROOT / parent["path"]) != parent["sha256"]:
        raise SystemExit("parent integrity contract drift")
    expected = [
        "cmi-no-memory", "cmi-full-history", "cmi-vector-memory",
        "cmi-summary-memory", "cmi-graph-memory",
    ]
    if proposal["eligible_method_order"] != expected:
        raise SystemExit("eligible method order drift")
    if set(proposal["selection_contract"]) != set(expected):
        raise SystemExit("selection contract coverage drift")
    if len(proposal["upstream_file_identities"]) != 8 or any(
        len(value) != 64 for value in proposal["upstream_file_identities"].values()
    ):
        raise SystemExit("upstream file identities incomplete")
    calls = proposal["matched_calls"]
    if (
        calls["answer_temperature"], calls["answer_max_output_tokens"],
        calls["embedding_dimensions"], calls["attempts_per_call"], calls["automatic_retries"],
    ) != (0.0, 600, 1024, 1, 0):
        raise SystemExit("matched call contract drift")
    denominator = proposal["future_denominator"]
    if (
        denominator["examples"], denominator["eligible_methods"], denominator["seeds"],
        denominator["eligible_rows_per_seed"], denominator["eligible_rows_total"],
        denominator["blocked_method_rows_total"], denominator["full_registered_rows"],
    ) != (87, 5, [0, 1, 2], 435, 1305, 522, 1827):
        raise SystemExit("future denominator drift")
    observations = proposal["current_observations"]
    if observations["official_values_used"] or any(
        observations[key] != 0
        for key in ("real_answer_calls", "real_embedding_calls", "real_prediction_rows", "scores_observed")
    ):
        raise SystemExit("proposal contains premature result evidence")
    if "authorizes no server file creation" not in proposal["authorization"]:
        raise SystemExit("proposal authorization boundary missing")
    print(json.dumps({
        "status": "PASS",
        "proposal_sha256": sha256(PATH),
        "implementation_sha256": sha256(ROOT / proposal["implementation"]),
        "eligible_methods": len(expected),
        "future_rows": denominator["full_registered_rows"],
        "real_calls": observations["real_answer_calls"] + observations["real_embedding_calls"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

