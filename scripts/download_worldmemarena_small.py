#!/usr/bin/env python3
"""Download and verify the frozen WorldMemArena small split.

The script resolves the 150 IDs from the pinned selector, downloads only the
corresponding sample JSON and image trees, and writes a deterministic manifest.
It intentionally does not run any benchmark or inspect answers for selection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

from huggingface_hub import HfApi, hf_hub_download, snapshot_download


REPO_ID = "LCZZZZ/WorldMemArena"
REVISION = "e2148757921fc7e2d66d8ed899823b763227c341"
EXPECTED_IDS = 150
EXPECTED_FILES = 5557
EXPECTED_BYTES = 3_855_814_942


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--max-workers", type=int, default=4)
    args = parser.parse_args()

    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    selector_path = Path(
        hf_hub_download(
            REPO_ID,
            "small_ids.json",
            repo_type="dataset",
            revision=REVISION,
            local_dir=destination,
        )
    )
    sample_ids = sorted(set(json.loads(selector_path.read_text(encoding="utf-8"))))
    if len(sample_ids) != EXPECTED_IDS:
        raise SystemExit(f"expected {EXPECTED_IDS} IDs, found {len(sample_ids)}")

    api_info = HfApi().dataset_info(REPO_ID, revision=REVISION, files_metadata=True)
    if api_info.sha != REVISION:
        raise SystemExit(f"revision mismatch: {api_info.sha}")

    selected = [
        sibling
        for sibling in api_info.siblings
        if sibling.rfilename in {"README.md", "small_ids.json"}
        or any(
            sibling.rfilename.endswith(f"/{sample_id}.json")
            or f"/images/{sample_id}/" in sibling.rfilename
            for sample_id in sample_ids
        )
    ]
    selected_paths = sorted(sibling.rfilename for sibling in selected)
    selected_bytes = sum(int(sibling.size or 0) for sibling in selected)
    json_ids = {
        PurePosixPath(path).stem
        for path in selected_paths
        if path.endswith(".json") and path != "small_ids.json"
    }
    if json_ids != set(sample_ids):
        raise SystemExit(f"sample path mismatch: missing={sorted(set(sample_ids) - json_ids)}")
    if len(selected_paths) != EXPECTED_FILES or selected_bytes != EXPECTED_BYTES:
        raise SystemExit(
            "upstream selection changed: "
            f"files={len(selected_paths)}/{EXPECTED_FILES}, "
            f"bytes={selected_bytes}/{EXPECTED_BYTES}"
        )

    allow_patterns = ["README.md", "small_ids.json"]
    for sample_id in sample_ids:
        allow_patterns.extend([f"**/{sample_id}.json", f"**/images/{sample_id}/**"])

    snapshot_download(
        REPO_ID,
        repo_type="dataset",
        revision=REVISION,
        local_dir=destination,
        allow_patterns=allow_patterns,
        max_workers=args.max_workers,
    )

    files = [
        path
        for path in sorted(destination.rglob("*"))
        if path.is_file()
        and ".cache" not in path.relative_to(destination).parts
        and path.name != "dataset-manifest.json"
    ]
    actual_paths = [path.relative_to(destination).as_posix() for path in files]
    if actual_paths != selected_paths:
        missing = sorted(set(selected_paths) - set(actual_paths))
        extra = sorted(set(actual_paths) - set(selected_paths))
        raise SystemExit(f"downloaded path mismatch: missing={missing[:10]} extra={extra[:10]}")

    entries = [
        {
            "path": path.relative_to(destination).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in files
    ]
    actual_bytes = sum(entry["bytes"] for entry in entries)
    if actual_bytes != EXPECTED_BYTES:
        raise SystemExit(f"downloaded byte mismatch: {actual_bytes}/{EXPECTED_BYTES}")

    manifest = {
        "schema_version": "agentenhance.dataset_manifest.v1",
        "repository": REPO_ID,
        "revision": REVISION,
        "split": "small",
        "sample_ids": sample_ids,
        "sample_id_count": len(sample_ids),
        "file_count": len(entries),
        "total_bytes": actual_bytes,
        "files": entries,
    }
    manifest_path = destination / "dataset-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "destination": str(destination),
        "revision": REVISION,
        "sample_id_count": len(sample_ids),
        "file_count": len(entries),
        "total_bytes": actual_bytes,
        "manifest_sha256": sha256_file(manifest_path),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
