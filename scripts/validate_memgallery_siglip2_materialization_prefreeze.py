#!/usr/bin/env python3
"""Validate the frozen, gated SigLIP2 materialization contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "memgallery-siglip2-model-materialization-prefreeze.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    contract = json.loads(PATH.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_AWAITING_WAVE1_DATA_AND_OWNERSHIP_GATES":
        raise SystemExit("SigLIP2 materialization is not frozen behind all gates")
    manifest = contract["prefetch_manifest"]
    if manifest["sha256"] == "TO_BE_BOUND_AFTER_MANIFEST_FREEZE":
        raise SystemExit("SigLIP2 prefetch manifest hash is not bound")
    if sha256_file(ROOT / manifest["path"]) != manifest["sha256"]:
        raise SystemExit("SigLIP2 prefetch manifest drift")
    implementation = contract["implementation"]
    for key, hash_key in (("downloader", "downloader_sha256"), ("unit_test", "unit_test_sha256")):
        if sha256_file(ROOT / implementation[key]) != implementation[hash_key]:
            raise SystemExit(f"SigLIP2 implementation drift: {implementation[key]}")
    model = contract["model"]
    if (model["expected_file_count"], model["expected_total_bytes"], model["lfs_sha256_files"], model["git_blob_sha1_files"]) != (9, 1540625721, 3, 6):
        raise SystemExit("SigLIP2 materialization cardinality drift")
    if len(contract["scheduler"]["required_observations"]) != 5:
        raise SystemExit("SigLIP2 scheduler observations incomplete")
    if contract["execution_contract"]["network_retry_count"] != 0:
        raise SystemExit("SigLIP2 materialization permits retries")
    state = contract["current_state"]
    if state["ownership_successor_accepted"] or state["scheduler_gate_open"]:
        raise SystemExit("SigLIP2 gates are prematurely open")
    if any(state[key] != 0 for key in ("downloaded_files", "downloaded_bytes", "network_requests", "numeric_rows")):
        raise SystemExit("SigLIP2 materialization contains premature execution")
    print(json.dumps({
        "status": "PASS", "contract_sha256": sha256_file(PATH),
        "manifest_sha256": manifest["sha256"], "files": model["expected_file_count"],
        "bytes": model["expected_total_bytes"], "scheduler_gate_open": state["scheduler_gate_open"],
        "downloaded_bytes": state["downloaded_bytes"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
