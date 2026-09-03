#!/usr/bin/env python3
"""Materialize one frozen Hugging Face snapshot with fail-closed evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_project_path(path: Path, leaf: tuple[str, ...]) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"path must be absolute and not a symlink: {path}")
    parts = path.parts
    for index in range(len(parts) - len(leaf) + 1):
        if parts[index : index + len(leaf)] == leaf:
            return
    raise ValueError(f"path is outside the required project scope {leaf}: {path}")


def resolve_manifest_path(raw_path: str) -> Path:
    """Resolve an environment-backed contract path and reject unresolved variables."""
    expanded = os.path.expandvars(raw_path)
    if "$" in expanded:
        raise ValueError(f"unresolved environment variable in manifest path: {raw_path}")
    return Path(expanded)


def repository_files(root: Path) -> list[Path]:
    rows = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts[:2] == (".cache", "huggingface"):
            continue
        rows.append(path)
    return sorted(rows, key=lambda path: path.relative_to(root).as_posix())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefetch-manifest", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()

    manifest_path = args.prefetch_manifest.resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("status") != "FROZEN_BEFORE_DOWNLOAD":
        raise SystemExit("prefetch manifest is not frozen")
    matches = [row for row in payload.get("models", []) if row["repository"] == args.repository]
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one model manifest row: {args.repository}")
    model: dict[str, Any] = matches[0]

    target = resolve_manifest_path(model["expected_local_path"])
    evidence_root = args.evidence_root.resolve()
    validate_project_path(target, ("AgentEnhance", "cache", "models"))
    validate_project_path(evidence_root, ("AgentEnhance", "runs"))
    if target.exists():
        raise SystemExit(f"refusing existing model target: {target}")
    if evidence_root.exists():
        raise SystemExit(f"refusing existing evidence root: {evidence_root}")
    evidence_root.mkdir(parents=True)

    started_at = now()
    try:
        from huggingface_hub import HfApi, snapshot_download

        info = HfApi().model_info(args.repository, revision=model["revision"])
        if info.sha != model["revision"]:
            raise RuntimeError(
                f"resolved revision mismatch: expected {model['revision']}, got {info.sha}"
            )
        resolved = Path(
            snapshot_download(
                repo_id=args.repository,
                revision=model["revision"],
                local_dir=target,
                allow_patterns=model["allow_patterns"],
            )
        ).resolve()
        if resolved != target.resolve():
            raise RuntimeError(f"snapshot resolved outside frozen target: {resolved}")

        files = repository_files(target)
        total_bytes = sum(path.stat().st_size for path in files)
        expected_files = model.get("expected_files")
        if expected_files is not None:
            expected_by_path = {
                str(row["path"]): int(row["bytes"]) for row in expected_files
            }
            observed_by_path = {
                path.relative_to(target).as_posix(): path.stat().st_size for path in files
            }
            if observed_by_path != expected_by_path:
                raise RuntimeError("selected model file paths or per-file byte sizes mismatch")
        if len(files) != int(model["expected_file_count"]):
            raise RuntimeError(
                f"file count mismatch: expected {model['expected_file_count']}, got {len(files)}"
            )
        if total_bytes != int(model["expected_total_bytes"]):
            raise RuntimeError(
                f"byte count mismatch: expected {model['expected_total_bytes']}, got {total_bytes}"
            )

        inventory = []
        for path in files:
            inventory.append(
                {
                    "path": path.relative_to(target).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        result = {
            "schema_version": "agentenhance.hf_model_materialization.v1",
            "status": "TERMINAL_ACCEPTED",
            "repository": args.repository,
            "revision": model["revision"],
            "target": str(target),
            "source_manifest": str(manifest_path),
            "source_manifest_sha256": sha256_file(manifest_path),
            "started_at": started_at,
            "finished_at": now(),
            "file_count": len(files),
            "total_bytes": total_bytes,
            "files": inventory,
        }
        result_path = evidence_root / "model-materialization.json"
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        model_sums_path = evidence_root / "MODEL_SHA256SUMS"
        model_sums_path.write_text(
            "".join(f"{row['sha256']}  {target / row['path']}\n" for row in inventory),
            encoding="utf-8",
        )
        (evidence_root / "EVIDENCE_SHA256SUMS").write_text(
            f"{sha256_file(result_path)}  {result_path}\n"
            f"{sha256_file(model_sums_path)}  {model_sums_path}\n",
            encoding="utf-8",
        )
        (evidence_root / "TERMINAL_ACCEPTED").touch()
        print(json.dumps({key: result[key] for key in ("status", "repository", "revision", "file_count", "total_bytes")}, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.hf_model_materialization_failure.v1",
            "status": "TERMINAL_REJECTED",
            "repository": args.repository,
            "revision": model["revision"],
            "target": str(target),
            "source_manifest": str(manifest_path),
            "source_manifest_sha256": sha256_file(manifest_path),
            "started_at": started_at,
            "finished_at": now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "partial_target_retained": target.exists(),
            "cleanup_authorized": False,
        }
        failure_path = evidence_root / "model-materialization-failure.json"
        failure_path.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (evidence_root / "EVIDENCE_SHA256SUMS").write_text(
            f"{sha256_file(failure_path)}  {failure_path}\n",
            encoding="utf-8",
        )
        (evidence_root / "TERMINAL_REJECTED").touch()
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
