#!/usr/bin/env python3
"""Fetch a paginated immutable Hugging Face dataset tree as a local manifest."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path


NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')
IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--manifest-id", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--license", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def fetch_tree(repo_id: str, revision: str) -> list[dict]:
    encoded_repo = urllib.parse.quote(repo_id, safe="/")
    encoded_revision = urllib.parse.quote(revision, safe="")
    url = (
        f"https://huggingface.co/api/datasets/{encoded_repo}/tree/{encoded_revision}"
        "?recursive=1&limit=100"
    )
    entries: list[dict] = []
    seen_urls: set[str] = set()
    while url:
        if url in seen_urls:
            raise RuntimeError("Hugging Face pagination loop detected")
        seen_urls.add(url)
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "AgentEnhance-manifest/1"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status != 200:
                raise RuntimeError(f"unexpected Hugging Face status: {response.status}")
            page = json.load(response)
            if not isinstance(page, list):
                raise RuntimeError("Hugging Face tree response is not a list")
            entries.extend(page)
            link = response.headers.get("Link", "")
        match = NEXT_LINK.search(link)
        url = match.group(1) if match else ""
    return entries


def normalize_files(entries: list[dict]) -> list[dict]:
    files: list[dict] = []
    for entry in entries:
        if entry.get("type") != "file":
            continue
        path = entry.get("path")
        oid = entry.get("oid")
        size = entry.get("size")
        if not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts:
            raise RuntimeError(f"unsafe or missing path: {path!r}")
        if not isinstance(oid, str) or len(oid) != 40:
            raise RuntimeError(f"invalid Git oid for {path}")
        if not isinstance(size, int) or size < 0:
            raise RuntimeError(f"invalid size for {path}")
        record: dict[str, object] = {"path": path, "bytes": size, "git_oid": oid}
        lfs = entry.get("lfs")
        if lfs is not None:
            lfs_oid = lfs.get("oid")
            lfs_size = lfs.get("size")
            pointer_size = lfs.get("pointerSize")
            if not isinstance(lfs_oid, str) or len(lfs_oid) != 64:
                raise RuntimeError(f"invalid LFS SHA-256 for {path}")
            if lfs_size != size:
                raise RuntimeError(f"LFS and entry size disagree for {path}")
            if not isinstance(pointer_size, int) or pointer_size <= 0:
                raise RuntimeError(f"invalid LFS pointer size for {path}")
            record.update(
                {
                    "lfs_sha256": lfs_oid,
                    "lfs_pointer_bytes": pointer_size,
                }
            )
        xet_hash = entry.get("xetHash")
        if xet_hash is not None:
            if not isinstance(xet_hash, str) or len(xet_hash) != 64:
                raise RuntimeError(f"invalid Xet hash for {path}")
            record["xet_hash"] = xet_hash
        files.append(record)
    files.sort(key=lambda item: str(item["path"]))
    paths = [str(item["path"]) for item in files]
    if len(paths) != len(set(paths)):
        raise RuntimeError("duplicate file paths in Hugging Face tree")
    return files


def build_manifest(args: argparse.Namespace, files: list[dict]) -> dict:
    suffix_counts = Counter(Path(str(item["path"])).suffix.lower() for item in files)
    dialog_files = [item for item in files if str(item["path"]).startswith("data/dialog/")]
    image_files = [
        item
        for item in files
        if str(item["path"]).startswith("data/image/")
        and Path(str(item["path"])).suffix.lower() in IMAGE_SUFFIXES
    ]
    lfs_files = [item for item in files if "lfs_sha256" in item]
    return {
        "schema_version": "agentenhance.hf_dataset_prefetch_manifest.v1",
        "manifest_id": args.manifest_id,
        "status": "FROZEN_BEFORE_DOWNLOAD",
        "observed_at": args.observed_at,
        "source": {
            "provider": "Hugging Face official dataset repository API",
            "repository": args.repo_id,
            "revision": args.revision,
            "license": args.license,
            "tree_api": (
                f"https://huggingface.co/api/datasets/{args.repo_id}/tree/{args.revision}"
                "?recursive=1&limit=100"
            ),
        },
        "expected": {
            "files": len(files),
            "bytes": sum(int(item["bytes"]) for item in files),
            "lfs_files": len(lfs_files),
            "lfs_bytes": sum(int(item["bytes"]) for item in lfs_files),
            "dialog_files": len(dialog_files),
            "image_files": len(image_files),
            "suffix_counts": dict(sorted(suffix_counts.items())),
        },
        "files": files,
        "download_policy": {
            "resource_gate": "Do not download while the Wave1 recovery2 controller or any project model service is active.",
            "target": "${AGENT_ENHANCE_REMOTE_ROOT}/datasets/raw/mem-gallery-af912dab",
            "transport": "Download directly on the server after the resource gate; any Mac-to-server transfer must use resumable SFTP limited to 4096 Kbit/s.",
            "verification": "Require exact revision, path set, byte count, and SHA-256 for every LFS object before any static-track lifecycle or numerical run.",
            "retention": "Dataset files and this manifest are permanent evidence and are never model-cleanup targets.",
        },
    }


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main() -> int:
    args = parse_args()
    entries = fetch_tree(args.repo_id, args.revision)
    files = normalize_files(entries)
    manifest = build_manifest(args, files)
    atomic_write(args.output.resolve(), manifest)
    print(json.dumps({"output": str(args.output), **manifest["expected"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
