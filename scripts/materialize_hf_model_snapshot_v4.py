#!/usr/bin/env python3
"""Materialize an exact HF snapshot with frozen LFS or Git-blob identities."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, BinaryIO

from materialize_hf_model_snapshot_v3 import (
    BLOCK_BYTES,
    file_url,
    now,
    observed_files,
    resolve_manifest_path,
    sha256_file,
    validate_project_path,
    validate_relative_file,
)


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
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ValueError("expected model paths must be unique and sorted")
    for row in expected:
        validate_relative_file(str(row["path"]))
        if int(row["bytes"]) < 0:
            raise ValueError(f"invalid frozen byte size for {row['path']}")
        sha256 = row.get("sha256")
        git_blob_sha1 = row.get("git_blob_sha1")
        if (sha256 is None) == (git_blob_sha1 is None):
            raise ValueError(f"exactly one frozen content identity is required: {row['path']}")
        if sha256 is not None and (
            len(str(sha256)) != 64
            or any(char not in "0123456789abcdef" for char in str(sha256))
        ):
            raise ValueError(f"invalid frozen SHA-256 for {row['path']}")
        if git_blob_sha1 is not None and (
            len(str(git_blob_sha1)) != 40
            or any(char not in "0123456789abcdef" for char in str(git_blob_sha1))
        ):
            raise ValueError(f"invalid frozen Git blob SHA-1 for {row['path']}")
    if sum(int(row["bytes"]) for row in expected) != int(model["expected_total_bytes"]):
        raise ValueError("expected total byte size mismatch")
    revision = str(model["revision"])
    if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
        raise ValueError("revision must be an immutable 40-character Git commit")
    return model


def stream_exact_file(
    source: BinaryIO, destination: Path, expected_bytes: int
) -> tuple[int, str, str]:
    observed_bytes = 0
    sha256 = hashlib.sha256()
    git_blob_sha1 = hashlib.sha1()
    git_blob_sha1.update(f"blob {expected_bytes}\0".encode("ascii"))
    with destination.open("xb") as handle:
        while True:
            block = source.read(BLOCK_BYTES)
            if not block:
                break
            observed_bytes += len(block)
            if observed_bytes > expected_bytes:
                raise RuntimeError(f"download exceeded frozen byte size: {destination}")
            sha256.update(block)
            git_blob_sha1.update(block)
            handle.write(block)
        handle.flush()
        os.fsync(handle.fileno())
    return observed_bytes, sha256.hexdigest(), git_blob_sha1.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefetch-manifest", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
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
    if target.exists() or evidence_root.exists():
        raise SystemExit("refusing existing model target or evidence root")
    target.mkdir(parents=True)
    evidence_root.mkdir(parents=True)

    started_at = now()
    attempts: list[dict[str, Any]] = []
    try:
        inventory: list[dict[str, Any]] = []
        for row in model["expected_files"]:
            relative_path = str(row["path"])
            final = target.joinpath(*validate_relative_file(relative_path).parts)
            final.parent.mkdir(parents=True, exist_ok=True)
            partial = final.with_name(final.name + ".partial")
            requested_url = file_url(args.repository, str(model["revision"]), relative_path)
            request = urllib.request.Request(
                requested_url, headers={"User-Agent": "AgentEnhance/1.0"}
            )
            attempt: dict[str, Any] = {
                "path": relative_path,
                "logical_request_attempt": 1,
                "retry_count": 0,
            }
            attempts.append(attempt)
            with urllib.request.urlopen(request, timeout=args.timeout_seconds) as response:
                final_url = urllib.parse.urlparse(response.geturl())
                attempt.update(
                    {
                        "http_status": response.status,
                        "redirected": response.geturl() != requested_url,
                        "final_scheme": final_url.scheme,
                        "final_hostname": final_url.hostname,
                    }
                )
                if response.status != 200 or final_url.scheme != "https":
                    raise RuntimeError(f"unexpected HTTP response for {relative_path}")
                observed_bytes, observed_sha256, observed_git_blob_sha1 = stream_exact_file(
                    response, partial, int(row["bytes"])
                )
            attempt.update(
                {
                    "observed_bytes": observed_bytes,
                    "observed_sha256": observed_sha256,
                    "observed_git_blob_sha1": observed_git_blob_sha1,
                }
            )
            if observed_bytes != int(row["bytes"]):
                raise RuntimeError(f"byte size mismatch for {relative_path}")
            if row.get("sha256") is not None and observed_sha256 != row["sha256"]:
                raise RuntimeError(f"LFS SHA-256 mismatch for {relative_path}")
            if row.get("git_blob_sha1") is not None and observed_git_blob_sha1 != row[
                "git_blob_sha1"
            ]:
                raise RuntimeError(f"Git blob SHA-1 mismatch for {relative_path}")
            partial.replace(final)
            inventory.append(
                {
                    "path": relative_path,
                    "bytes": observed_bytes,
                    "sha256": observed_sha256,
                    "git_blob_sha1": observed_git_blob_sha1,
                    "frozen_identity_type": (
                        "lfs-sha256" if row.get("sha256") is not None else "git-blob-sha1"
                    ),
                }
            )
        expected_paths = [str(row["path"]) for row in model["expected_files"]]
        if observed_files(target) != expected_paths:
            raise RuntimeError("materialized model paths differ from the frozen expected files")
        result = {
            "schema_version": "agentenhance.hf_model_materialization.v4",
            "status": "TERMINAL_ACCEPTED",
            "repository": args.repository,
            "revision": model["revision"],
            "target": str(target),
            "source_manifest": str(manifest_path),
            "source_manifest_sha256": sha256_file(manifest_path),
            "started_at": started_at,
            "finished_at": now(),
            "network_retry_count": 0,
            "logical_requests_per_file": 1,
            "file_count": len(inventory),
            "total_bytes": sum(row["bytes"] for row in inventory),
            "frozen_lfs_sha256_files": sum(row.get("sha256") is not None for row in model["expected_files"]),
            "frozen_git_blob_sha1_files": sum(row.get("git_blob_sha1") is not None for row in model["expected_files"]),
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
        (evidence_root / "EVIDENCE_SHA256SUMS").write_text(
            f"{sha256_file(result_path)}  {result_path}\n"
            f"{sha256_file(model_sums_path)}  {model_sums_path}\n",
            encoding="utf-8",
        )
        (evidence_root / "TERMINAL_ACCEPTED").touch()
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in (
                        "status",
                        "repository",
                        "revision",
                        "file_count",
                        "total_bytes",
                        "network_retry_count",
                        "frozen_lfs_sha256_files",
                        "frozen_git_blob_sha1_files",
                    )
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.hf_model_materialization_failure.v4",
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
