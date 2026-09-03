#!/usr/bin/env python3
"""Validate the immutable Mem-Gallery dataset tree manifest."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "comparisons" / "memgallery-data-prefetch-manifest.v1.json"
CONTRACT_PATH = ROOT / "comparisons" / "post-wma-cross-track-completion-prefreeze.v1.json"
IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("status") != "FROZEN_BEFORE_DOWNLOAD":
        raise SystemExit("Mem-Gallery manifest is not frozen before download")
    source = manifest["source"]
    if source != {
        "provider": "Hugging Face official dataset repository API",
        "repository": "Ethan-Bei/Mem-Gallery",
        "revision": "af912daba984e896e253016b7c7e334ef92c2a6f",
        "license": "mit",
        "tree_api": "https://huggingface.co/api/datasets/Ethan-Bei/Mem-Gallery/tree/af912daba984e896e253016b7c7e334ef92c2a6f?recursive=1&limit=100",
    }:
        raise SystemExit("Mem-Gallery source identity drift")

    files = manifest["files"]
    paths = [item["path"] for item in files]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise SystemExit("dataset paths must be unique and sorted")
    if any(path.startswith("/") or ".." in Path(path).parts for path in paths):
        raise SystemExit("unsafe dataset path")
    if any(len(item["git_oid"]) != 40 for item in files):
        raise SystemExit("invalid Git oid")
    lfs = [item for item in files if "lfs_sha256" in item]
    if any(len(item["lfs_sha256"]) != 64 or item["lfs_pointer_bytes"] <= 0 for item in lfs):
        raise SystemExit("invalid LFS identity")
    if any("xet_hash" in item and len(item["xet_hash"]) != 64 for item in files):
        raise SystemExit("invalid Xet identity")

    dialog = [item for item in files if item["path"].startswith("data/dialog/")]
    images = [
        item
        for item in files
        if item["path"].startswith("data/image/")
        and Path(item["path"]).suffix.lower() in IMAGE_SUFFIXES
    ]
    suffix_counts = Counter(Path(item["path"]).suffix.lower() for item in files)
    observed = {
        "files": len(files),
        "bytes": sum(item["bytes"] for item in files),
        "lfs_files": len(lfs),
        "lfs_bytes": sum(item["bytes"] for item in lfs),
        "dialog_files": len(dialog),
        "image_files": len(images),
        "suffix_counts": dict(sorted(suffix_counts.items())),
    }
    if observed != manifest["expected"]:
        raise SystemExit(f"dataset aggregate mismatch: {observed}")
    if observed != {
        "files": 1515,
        "bytes": 545845389,
        "lfs_files": 1491,
        "lfs_bytes": 542950920,
        "dialog_files": 20,
        "image_files": 1490,
        "suffix_counts": {"": 3, ".jpg": 1228, ".json": 20, ".md": 1, ".png": 263},
    }:
        raise SystemExit("frozen Mem-Gallery cardinality drift")
    if any("lfs_sha256" not in item for item in images):
        raise SystemExit("every image must have an immutable LFS SHA-256")

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    static = next(item for item in contract["tracks"] if item["track_id"] == "memgallery-static-matched-v1")
    if static["matched_protocol"]["questions_expected"] != 1711:
        raise SystemExit("Mem-Gallery question denominator drift")
    policy = manifest["download_policy"]
    if "Wave1 recovery2" not in policy["resource_gate"]:
        raise SystemExit("dataset download lacks the active Wave1 exclusion gate")
    if "4096 Kbit/s" not in policy["transport"]:
        raise SystemExit("Mac-to-server transfer limit is missing")
    if "never model-cleanup targets" not in policy["retention"]:
        raise SystemExit("dataset retention boundary is missing")

    print(
        json.dumps(
            {
                "status": "PASS",
                "revision": source["revision"],
                "manifest_sha256": hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
                **observed,
                "questions_expected": 1711,
                "downloaded_bytes": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
