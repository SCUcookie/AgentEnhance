#!/usr/bin/env python3
"""Validate the synthetic-only Causal-LoCoMo lifecycle proposal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "causal-locomo-lifecycle-controller-proposal.v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    proposal = json.loads(PATH.read_text(encoding="utf-8"))
    if proposal.get("state") != "PROPOSED_SYNTHETIC_ONLY_REAL_MODE_DENIED":
        raise SystemExit("lifecycle proposal state drift")
    for parent in proposal["parents"]:
        if sha256(ROOT / parent["path"]) != parent["sha256"]:
            raise SystemExit(f"lifecycle parent drift: {parent['path']}")
    acceptance = proposal["synthetic_acceptance"]
    if (
        acceptance["seeds"], acceptance["methods"],
        acceptance["accepted_methods_per_qid_seed"],
        acceptance["protocol_blocked_methods_per_qid_seed"],
        acceptance["real_mode_implemented"], acceptance["real_mode_creates_paths"],
        acceptance["gold_fields_in_model_prompts"], acceptance["automatic_retries"],
    ) != ([0, 1, 2], 7, 5, 2, False, False, 0, 0):
        raise SystemExit("lifecycle acceptance drift")
    observations = proposal["current_observations"]
    if any(observations[key] != 0 for key in (
        "real_roots", "real_answer_calls", "real_embedding_calls",
        "real_prediction_rows", "scores_observed",
    )):
        raise SystemExit("lifecycle proposal contains real observations")
    if "Real mode is unimplemented" not in proposal["authorization"]:
        raise SystemExit("lifecycle authorization boundary missing")
    print(json.dumps({
        "status": "PASS",
        "proposal_sha256": sha256(PATH),
        "implementation_sha256": sha256(ROOT / proposal["implementation"]),
        "synthetic_tests": observations["synthetic_test_cases"],
        "real_mode_implemented": acceptance["real_mode_implemented"],
        "scores_observed": observations["scores_observed"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

