#!/usr/bin/env python3
"""Materialize one frozen Hugging Face model using exact files and hashes.

This v2 downloader intentionally avoids ``snapshot_download`` so that the
control plane, rather than a client library, owns the retry policy.  Every
listed file receives one logical HTTP request, is streamed sequentially, and
must match both its frozen byte size and SHA-256 before acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO


BLOCK_BYTES = 8 * 1024 * 1024


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_project_path(path: Path, leaf: tuple[str, ...]) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"path must be absolute and not a symlink: {path}")
    parts = path.parts
    for index in range(len(parts) - len(leaf) + 1):
        if parts[index : index + len(leaf)] == leaf:
            return
    raise ValueError(f"path is outside the required project scope {leaf}: {path}")


def resolve_manifest_path(raw_path: str) -> Path:
    expanded = os.path.expandvars(raw_path)
    if "$" in expanded:
        raise ValueError(f"unresolved environment variable in manifest path: {raw_path}")
    return Path(expanded)


def select_model(payload: dict[str, Any], repository: str) -> dict[str, Any]:
    if payload.get("status") != "FROZEN_BEFORE_DOWNLOAD":
        raise ValueError("prefetch manifest is not frozen")
    matches = [row for row in payload.get("models", []) if row.get("repository") == repository]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one model manifest row: {repository}")
    model = matches[0]
    expected = model.get("expected_files", [])
    if not expected or len(expected) != int(model["expected_file_count"]):
        raise ValueError("expected file cardinality mismatch")
    paths = [str(row["path"]) for row in expected]
    if paths != list(model["allow_patterns"]) or len(paths) != len(set(paths)):
        raise ValueError("expected files must exactly equal the unique ordered allowlist")
    for row in expected:
        path = Path(str(row["path"]))
        if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
            raise ValueError(f"unsafe or nested model file path: {path}")
        digest = str(row["sha256"])
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"invalid frozen SHA-256 for {path}")
        if int(row["bytes"]) < 0:
            raise ValueError(f"invalid frozen byte size for {path}")
    if sum(int(row["bytes"]) for row in expected) != int(model["expected_total_bytes"]):
        raise ValueError("expected total byte size mismatch")
    revision = str(model["revision"])
    if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
        raise ValueError("revision must be an immutable 40-character Git commit")
    return model


def file_url(repository: str, revision: str, relative_path: str) -> str:
    repo = "/".join(urllib.parse.quote(part, safe="") for part in repository.split("/"))
    revision_encoded = urllib.parse.quote(revision, safe="")
    path_encoded = urllib.parse.quote(relative_path, safe="")
    return f"https://huggingface.co/{repo}/resolve/{revision_encoded}/{path_encoded}?download=true"


def stream_exact_file(source: BinaryIO, destination: Path, expected_bytes: int) -> tuple[int, str]:
    observed_bytes = 0
    digest = hashlib.sha256()
    with destination.open("xb") as handle:
        while True:
            block = source.read(BLOCK_BYTES)
            if not block:
                break
            observed_bytes += len(block)
            if observed_bytes > expected_bytes:
                raise RuntimeError(f"download exceeded frozen byte size: {destination.name}")
            digest.update(block)
            handle.write(block)
        handle.flush()
        os.fsync(handle.fileno())
    return observed_bytes, digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefetch-manifest", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args()

    manifest_path = args.prefetch_manifest.resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    model = select_model(payload, args.repository)
    target = resolve_manifest_path(str(model["expected_local_path"]))
    evidence_root = args.evidence_root.resolve()
    validate_project_path(target, ("AgentEnhance", "cache", "models"))
    validate_project_path(evidence_root, ("AgentEnhance", "runs"))
    if args.timeout_seconds <= 0:
        raise SystemExit("timeout must be positive")
    if target.exists():
        raise SystemExit(f"refusing existing model target: {target}")
    if evidence_root.exists():
        raise SystemExit(f"refusing existing evidence root: {evidence_root}")
    target.mkdir(parents=True)
    evidence_root.mkdir(parents=True)

    started_at = now()
    attempts: list[dict[str, Any]] = []
    try:
        inventory: list[dict[str, Any]] = []
        for row in model["expected_files"]:
            relative_path = str(row["path"])
            partial = target / f"{relative_path}.partial"
            final = target / relative_path
            url = file_url(args.repository, str(model["revision"]), relative_path)
            request = urllib.request.Request(url, headers={"User-Agent": "AgentEnhance/1.0"})
            attempt = {"path": relative_path, "logical_request_attempt": 1, "retry_count": 0}
            attempts.append(attempt)
            with urllib.request.urlopen(request, timeout=args.timeout_seconds) as response:
                observed_bytes, observed_sha256 = stream_exact_file(
                    response, partial, int(row["bytes"])
                )
            attempt["observed_bytes"] = observed_bytes
            attempt["observed_sha256"] = observed_sha256
            if observed_bytes != int(row["bytes"]):
                raise RuntimeError(f"byte size mismatch for {relative_path}")
            if observed_sha256 != str(row["sha256"]):
                raise RuntimeError(f"SHA-256 mismatch for {relative_path}")
            partial.replace(final)
            inventory.append(
                {"path": relative_path, "bytes": observed_bytes, "sha256": observed_sha256}
            )

        observed_names = sorted(path.name for path in target.iterdir() if path.is_file())
        expected_names = sorted(str(row["path"]) for row in model["expected_files"])
        if observed_names != expected_names:
            raise RuntimeError("materialized model paths differ from the frozen allowlist")
        result = {
            "schema_version": "agentenhance.hf_model_materialization.v2",
            "status": "TERMINAL_ACCEPTED",
            "repository": args.repository,
            "revision": model["revision"],
            "target": str(target),
            "source_manifest": str(manifest_path),
            "source_manifest_sha256": sha256_file(manifest_path),
            "started_at": started_at,
            "finished_at": now(),
            "network_retry_count": 0,
            "file_count": len(inventory),
            "total_bytes": sum(row["bytes"] for row in inventory),
            "files": inventory,
            "attempts": attempts,
        }
        result_path = evidence_root / "model-materialization.json"
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        model_sums_path = evidence_root / "MODEL_SHA256SUMS"
        model_sums_path.write_text(
            "".join(f"{row['sha256']}  {target / row['path']}\n" for row in inventory),
            encoding="utf-8",
        )
        evidence_sums = evidence_root / "EVIDENCE_SHA256SUMS"
        evidence_sums.write_text(
            f"{sha256_file(result_path)}  {result_path}\n"
            f"{sha256_file(model_sums_path)}  {model_sums_path}\n",
            encoding="utf-8",
        )
        (evidence_root / "TERMINAL_ACCEPTED").touch()
        print(json.dumps({key: result[key] for key in ("status", "repository", "revision", "file_count", "total_bytes", "network_retry_count")}, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.hf_model_materialization_failure.v2",
            "status": "TERMINAL_REJECTED",
            "repository": args.repository,
            "revision": model["revision"],
            "target": str(target),
            "source_manifest": str(manifest_path),
            "source_manifest_sha256": sha256_file(manifest_path),
            "started_at": started_at,
            "finished_at": now(),
            "network_retry_count": 0,
            "attempts": attempts,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "partial_target_retained": target.exists(),
            "cleanup_authorized": False,
        }
        failure_path = evidence_root / "model-materialization-failure.json"
        failure_path.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (evidence_root / "EVIDENCE_SHA256SUMS").write_text(
            f"{sha256_file(failure_path)}  {failure_path}\n", encoding="utf-8"
        )
        (evidence_root / "TERMINAL_REJECTED").touch()
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
