#!/usr/bin/env python3
"""Create a deterministic uncompressed tar from a verified dataset manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path, PurePosixPath


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def add_regular_file(archive: tarfile.TarFile, source: Path, arcname: str) -> None:
    info = tarfile.TarInfo(arcname)
    info.size = source.stat().st_size
    info.mode = 0o644
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.pax_headers = {}
    with source.open("rb") as handle:
        archive.addfile(info, handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("output_tar", type=Path)
    parser.add_argument("--manifest", default="dataset-manifest.json")
    args = parser.parse_args()

    root = args.dataset_root.resolve()
    output = args.output_tar.resolve()
    manifest_path = (root / args.manifest).resolve()
    if output.exists():
        raise SystemExit(f"refusing existing archive: {output}")
    if output.suffix != ".tar":
        raise SystemExit("output must use the .tar suffix")
    if root == output or root in output.parents:
        raise SystemExit("archive output must be outside the dataset tree")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = sorted(manifest["files"], key=lambda row: str(row["path"]))
    for row in rows:
        rel = str(row["path"])
        pure = PurePosixPath(rel)
        if pure.is_absolute() or ".." in pure.parts:
            raise SystemExit(f"unsafe manifest path: {rel}")
        source = root / rel
        if not source.is_file() or source.is_symlink():
            raise SystemExit(f"missing or non-regular source: {rel}")
        if source.stat().st_size != int(row["bytes"]):
            raise SystemExit(f"source size mismatch: {rel}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for row in rows:
            rel = str(row["path"])
            add_regular_file(archive, root / rel, rel)
        add_regular_file(archive, manifest_path, args.manifest)

    print(json.dumps({
        "status": "PACKAGED",
        "archive": str(output),
        "archive_bytes": output.stat().st_size,
        "archive_sha256": sha256_file(output),
        "manifest_sha256": sha256_file(manifest_path),
        "file_count_including_manifest": len(rows) + 1,
        "normalization": {
            "format": "PAX",
            "compression": "none",
            "mtime": 0,
            "uid": 0,
            "gid": 0,
            "mode": "0644",
            "order": "manifest path ascending, manifest last"
        }
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
