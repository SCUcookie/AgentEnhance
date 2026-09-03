#!/usr/bin/env python3
"""Verify an extracted dataset tree against an AgentEnhance file manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--manifest", default="dataset-manifest.json")
    args = parser.parse_args()

    root = args.dataset_root.resolve()
    manifest_path = (root / args.manifest).resolve()
    if root not in manifest_path.parents:
        raise SystemExit("manifest must be inside dataset root")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "agentenhance.dataset_manifest.v1":
        raise SystemExit("unsupported manifest schema")

    expected: dict[str, tuple[int, str]] = {}
    for row in manifest.get("files", []):
        rel = str(row["path"])
        pure = PurePosixPath(rel)
        if pure.is_absolute() or ".." in pure.parts or rel in expected:
            raise SystemExit(f"unsafe or duplicate manifest path: {rel}")
        expected[rel] = (int(row["bytes"]), str(row["sha256"]))

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path != manifest_path
        and ".cache" not in path.relative_to(root).parts
    }
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        extra = sorted(actual - set(expected))
        raise SystemExit(f"path mismatch: missing={missing[:10]} extra={extra[:10]}")

    total_bytes = 0
    for rel in sorted(expected):
        path = root / rel
        if path.is_symlink():
            raise SystemExit(f"symlink is not allowed: {rel}")
        expected_bytes, expected_sha = expected[rel]
        actual_bytes = path.stat().st_size
        if actual_bytes != expected_bytes:
            raise SystemExit(f"size mismatch: {rel}: {actual_bytes}/{expected_bytes}")
        actual_sha = sha256_file(path)
        if actual_sha != expected_sha:
            raise SystemExit(f"SHA-256 mismatch: {rel}")
        total_bytes += actual_bytes

    if len(expected) != int(manifest["file_count"]):
        raise SystemExit("manifest file_count mismatch")
    if total_bytes != int(manifest["total_bytes"]):
        raise SystemExit("manifest total_bytes mismatch")

    print(json.dumps({
        "status": "PASS",
        "dataset_root": str(root),
        "repository": manifest.get("repository"),
        "revision": manifest.get("revision"),
        "split": manifest.get("split"),
        "sample_id_count": manifest.get("sample_id_count"),
        "file_count": len(expected),
        "total_bytes": total_bytes,
        "manifest_sha256": sha256_file(manifest_path),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
