#!/usr/bin/env python3
"""Validate the result-free matched Mem-Gallery answer request contract."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons" / "memgallery-answer-contract-prefreeze.v1.json"
IMPLEMENTATION = ROOT / "scripts" / "memgallery_answer_contract.py"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    require(payload.get("status") == "FROZEN_REQUEST_ASSEMBLY_ONLY_AWAITING_ENDPOINT_LIFECYCLE", "status drift")
    bindings = payload.get("bound_inputs", [])
    require(len(bindings) == 3, "bound-input count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file(), f"missing bound input: {path}")
        require(sha256_file(path) == binding["sha256"], f"bound-input hash drift: {path}")
    spec = importlib.util.spec_from_file_location("memgallery_answer_contract", IMPLEMENTATION)
    require(spec is not None and spec.loader is not None, "cannot load answer implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = payload["upstream_authority"]["normalized_prompt_sha256"]
    require(sha256_text(module.SYSTEM_PROMPT) == expected["sys_prompt.txt"], "system prompt drift")
    for category in ("AR", "CD", "VS"):
        require(sha256_text(module.CATEGORY_CONSTRAINTS[category]) == expected[f"{category.lower()}_prompt.txt"], f"{category} prompt drift")
    model = payload.get("matched_model", {})
    require(module.ANSWER_MODEL == model.get("served_model"), "served model drift")
    require(module.ANSWER_TEMPERATURE == model.get("temperature") == 0.0, "temperature drift")
    require(module.ANSWER_MAX_OUTPUT_TOKENS == model.get("max_output_tokens") == 128, "output-token drift")
    validation = payload.get("validation", {})
    require(validation.get("synthetic_tests_passed") == 5, "test count drift")
    for field in ("endpoint_calls", "image_bytes_read", "predictions_observed", "scores_observed"):
        require(validation.get(field) == 0, f"request-only boundary drift: {field}")
    print(json.dumps({
        "status": "PASS",
        "contract_sha256": sha256_file(CONTRACT),
        "implementation_sha256": sha256_file(IMPLEMENTATION),
        "prompt_hashes": expected,
        "endpoint_calls": validation["endpoint_calls"],
        "scores_observed": validation["scores_observed"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
