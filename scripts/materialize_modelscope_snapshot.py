#!/usr/bin/env python3
"""Materialize one pinned ModelScope snapshot into a read-only model store."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from modelscope import snapshot_download


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--incoming-root", type=Path, required=True)
    parser.add_argument("--final-dir", type=Path, required=True)
    parser.add_argument("--max-workers", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.final_dir.exists():
        raise FileExistsError(f"refusing to overwrite final model directory: {args.final_dir}")
    args.incoming_root.mkdir(parents=True, exist_ok=True)
    partial = args.incoming_root / f"{args.final_dir.name}.partial.{args.revision[:12]}"
    partial.mkdir(parents=True, exist_ok=True)

    resolved = Path(
        snapshot_download(
            model_id=args.model_id,
            revision=args.revision,
            local_dir=str(partial),
            max_workers=args.max_workers,
        )
    ).resolve()
    if resolved != partial.resolve():
        raise RuntimeError(f"unexpected snapshot location: {resolved}")

    links = [path for path in partial.rglob("*") if path.is_symlink()]
    if links:
        raise RuntimeError(f"snapshot contains symlinks: {links[:3]}")

    files = [
        path
        for path in sorted(partial.rglob("*"))
        if path.is_file()
        and path.name not in {"MODEL_FILES_SHA256SUMS", "placement-manifest.json"}
    ]
    if not files:
        raise RuntimeError("downloaded snapshot contains no files")
    records = []
    for path in files:
        relative = path.relative_to(partial).as_posix()
        records.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})

    inventory = partial / "MODEL_FILES_SHA256SUMS"
    inventory.write_text(
        "".join(f"{record['sha256']}  {record['path']}\n" for record in records),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "model_placement_manifest.v1",
        "model_id": args.model_id,
        "source": "modelscope",
        "revision": args.revision,
        "materialized_at_utc": datetime.now(timezone.utc).isoformat(),
        "file_count": len(records),
        "total_bytes": sum(record["bytes"] for record in records),
        "model_files_inventory_sha256": sha256(inventory),
        "read_only_after_publish": True,
    }
    (partial / "placement-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    args.final_dir.parent.mkdir(parents=True, exist_ok=True)
    os.replace(partial, args.final_dir)
    for path in sorted(args.final_dir.rglob("*"), reverse=True):
        mode = path.stat().st_mode
        path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    mode = args.final_dir.stat().st_mode
    args.final_dir.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
