#!/usr/bin/env python3
"""Validate the exact SigLIP2 prefetch manifest for Mem-Gallery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from materialize_hf_model_snapshot_v4 import select_model


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "memgallery-siglip2-model-prefetch-manifest.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    payload = json.loads(PATH.read_text(encoding="utf-8"))
    parent = payload["parent_model_surface"]
    if sha256_file(ROOT / parent["path"]) != parent["sha256"]:
        raise SystemExit("SigLIP2 parent model surface drift")
    model = select_model(payload, "google/siglip2-base-patch16-384")
    if model["method_ids"] != ["m2a", "v-mem"]:
        raise SystemExit("SigLIP2 dependent-method drift")
    if (model["revision"], model["expected_file_count"], model["expected_total_bytes"]) != (
        "f775b65a79762255128c981547af89addcfe0f88", 9, 1540625721,
    ):
        raise SystemExit("SigLIP2 frozen identity drift")
    lfs = sum("sha256" in row for row in model["expected_files"])
    git = sum("git_blob_sha1" in row for row in model["expected_files"])
    if (lfs, git) != (3, 6):
        raise SystemExit("SigLIP2 content-identity partition drift")
    state = payload["current_state"]
    if any(state[key] != 0 for key in ("downloaded_files", "downloaded_bytes", "network_requests", "numeric_rows")):
        raise SystemExit("SigLIP2 manifest contains premature execution")
    if state["official_values_used"]:
        raise SystemExit("SigLIP2 manifest contains official values")
    print(json.dumps({
        "status": "PASS", "manifest_sha256": sha256_file(PATH),
        "revision": model["revision"], "files": model["expected_file_count"],
        "bytes": model["expected_total_bytes"], "lfs_sha256_files": lfs,
        "git_blob_sha1_files": git, "downloaded_bytes": state["downloaded_bytes"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
