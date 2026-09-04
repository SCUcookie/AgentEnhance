#!/usr/bin/env python3
"""Validate the mock-only Causal-LoCoMo endpoint client proposal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "causal-locomo-endpoint-client-proposal.v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    proposal = json.loads(PATH.read_text(encoding="utf-8"))
    if proposal.get("state") != "PROPOSED_MOCK_ONLY_NOT_FROZEN_NOT_AUTHORIZED":
        raise SystemExit("endpoint proposal state drift")
    parent = proposal["parent"]
    if sha256(ROOT / parent["path"]) != parent["sha256"]:
        raise SystemExit("endpoint proposal parent drift")
    surface = proposal["surface"]
    if (
        surface["chat_model"], surface["chat_temperature"], surface["chat_max_tokens"],
        surface["embedding_model_alias"], surface["embedding_dimensions"],
        surface["inputs_per_embedding_call"], surface["attempts_per_call"],
        surface["automatic_retries"], surface["max_response_bytes"],
    ) != (
        "Qwen3-VL-8B-Instruct", 0.0, 600, "text-embedding-3-small", 1024, 1, 1, 0, 16777216,
    ):
        raise SystemExit("endpoint surface drift")
    evidence = proposal["existing_compatibility_evidence"]
    if evidence["wma_embed1024_dimensions"] != 1024 or evidence["wma_embed1024_usage"] != {
        "prompt_tokens": 4, "completion_tokens": 0, "total_tokens": 4,
    }:
        raise SystemExit("existing response-shape evidence drift")
    observations = proposal["current_observations"]
    if any(observations[key] != 0 for key in (
        "real_chat_calls", "real_embedding_calls", "prediction_rows", "scores_observed",
    )):
        raise SystemExit("endpoint proposal contains real observations")
    if "authorizes no real endpoint request" not in proposal["authorization"]:
        raise SystemExit("endpoint proposal authorization boundary missing")
    print(json.dumps({
        "status": "PASS",
        "proposal_sha256": sha256(PATH),
        "implementation_sha256": sha256(ROOT / proposal["implementation"]),
        "real_calls": observations["real_chat_calls"] + observations["real_embedding_calls"],
        "scores_observed": observations["scores_observed"],
        "embedding_dimensions": surface["embedding_dimensions"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

