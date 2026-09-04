#!/usr/bin/env python3
"""Validate the additive cross-track ownership-ledger successor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "baseline-model-ownership-ledger.v2.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ledger = json.loads(PATH.read_text(encoding="utf-8"))
    if ledger.get("status") != "FROZEN_BEFORE_SIGLIP2_MATERIALIZATION_AND_ANY_MODEL_CLEANUP":
        raise SystemExit("ownership ledger v2 is not prospectively frozen")
    parent = ledger["supersedes"]
    if sha256_file(ROOT / parent["path"]) != parent["sha256"]:
        raise SystemExit("ownership ledger v1 drift")
    if len(ledger["protected_shared_assets_unchanged"]) != 2:
        raise SystemExit("protected shared-asset cardinality drift")
    if any(row["cleanup_eligible"] for row in ledger["protected_shared_assets_unchanged"]):
        raise SystemExit("protected shared model is cleanup eligible")

    expanded = {row["model_id"]: row for row in ledger["expanded_project_owned_dependents"]}
    if set(expanded) != {"wave2-gme-qwen2-vl-2b", "wave3-all-minilm-l6-v2"}:
        raise SystemExit("expanded existing-candidate surface drift")
    if expanded["wave2-gme-qwen2-vl-2b"]["new_required_dependents"] != [
        "memgallery-naive-rag", "memgallery-ngm", "memgallery-augustus", "memgallery-universalrag"
    ]:
        raise SystemExit("GME dependent expansion drift")
    if expanded["wave3-all-minilm-l6-v2"]["new_required_dependents"] != [
        "memgallery-a-mem", "memgallery-memoryos", "memgallery-v-mem"
    ]:
        raise SystemExit("MiniLM dependent expansion drift")
    if any(row["cleanup_eligible"] for row in expanded.values()):
        raise SystemExit("expanded model is cleanup eligible")

    if len(ledger["new_project_owned_candidates"]) != 1:
        raise SystemExit("new ownership candidate cardinality drift")
    siglip = ledger["new_project_owned_candidates"][0]
    if (
        siglip["model_id"], siglip["revision"], siglip["expected_files"],
        siglip["expected_bytes"], siglip["required_dependents"], siglip["cleanup_eligible"],
    ) != (
        "memgallery-vmem-siglip2-base-patch16-384",
        "f775b65a79762255128c981547af89addcfe0f88",
        9, 1540625721, ["memgallery-m2a", "memgallery-v-mem"], False,
    ):
        raise SystemExit("SigLIP2 ownership identity drift")
    if sha256_file(ROOT / siglip["prefetch_manifest"]) != siglip["prefetch_manifest_sha256"]:
        raise SystemExit("SigLIP2 prefetch identity drift")

    if ledger["effective_aggregate"] != {
        "project_owned_candidate_models": 8,
        "project_owned_expected_files": 99,
        "project_owned_expected_bytes": 28164467445,
        "protected_shared_models": 2,
        "new_candidate_models": 1,
        "expanded_existing_candidates": 2,
        "currently_cleanup_eligible_models": 0,
    }:
        raise SystemExit("ownership ledger v2 aggregate drift")
    state = ledger["current_state"]
    if state != {
        "siglip2_materialized": False,
        "memgallery_complete": False,
        "all_three_tracks_complete": False,
        "cleanup_eligible_models": 0,
        "mutation_performed": False,
    }:
        raise SystemExit("ownership ledger v2 contains premature state")
    if not ledger["cleanup_authorization"].startswith("None."):
        raise SystemExit("ownership ledger v2 accidentally authorizes cleanup")

    print(json.dumps({
        "status": "PASS", "ledger_sha256": sha256_file(PATH),
        "project_owned_candidates": ledger["effective_aggregate"]["project_owned_candidate_models"],
        "candidate_bytes": ledger["effective_aggregate"]["project_owned_expected_bytes"],
        "new_candidates": ledger["effective_aggregate"]["new_candidate_models"],
        "expanded_candidates": ledger["effective_aggregate"]["expanded_existing_candidates"],
        "cleanup_eligible_now": state["cleanup_eligible_models"],
        "mutation_performed": state["mutation_performed"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
