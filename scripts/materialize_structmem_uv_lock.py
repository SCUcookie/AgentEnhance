#!/usr/bin/env python3
"""Resolve the frozen StructMem dependency workspace twice with accepted uv."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKSPACE_BYTES = 1616
WORKSPACE_SHA256 = "aaadfad3524aad6b6659b8ac5d2f6e8a1c1dcb54d898fd73d3ee66f083b04e0b"
UPSTREAM_PYPROJECT_BYTES = 2698
UPSTREAM_PYPROJECT_SHA256 = "632334023335283070abb2eebfc5bece3eea11387724eaccb7aeda40732b97bb"
UV_SHA256 = "671793498fe0a545432e2524b6691ffb9eea4540d9fda43ca2f978df2dbf8426"
UV_VERSION_OUTPUT = "uv 0.12.9 (x86_64-unknown-linux-gnu)"
PYTHON_SHA256 = "db8630b1dda55498c4d254878d144e04d3c6fd82115b700c00a13c9029fdbd02"
PYTHON_VERSION_PREFIX = "3.11.0 | packaged by conda-forge |"
EXPECTED_DIRECT_DEPENDENCIES = 58


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_project_child(path: Path, project_root: Path, component: str) -> Path:
    resolved = path.resolve()
    expected = (project_root / component).resolve()
    if resolved == expected or expected not in resolved.parents or resolved.is_symlink():
        raise ValueError(f"path is outside {component}: {resolved}")
    return resolved


def lock_command(uv: Path, python: Path) -> list[str]:
    return [
        str(uv),
        "lock",
        "--python",
        str(python),
        "--no-python-downloads",
        "--no-cache",
        "--no-progress",
    ]


def normalized_name(value: str) -> str:
    return value.lower().replace("_", "-").replace(".", "-")


def seal(root: Path, record: dict[str, Any], accepted: bool) -> None:
    record_path = root / "lock-materialization.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    evidence = [
        path
        for path in sorted(root.iterdir())
        if path.is_file() and path.name not in {"EVIDENCE_SHA256SUMS", "TERMINAL_ACCEPTED", "TERMINAL_REJECTED"}
    ]
    (root / "EVIDENCE_SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in evidence),
        encoding="utf-8",
    )
    (root / ("TERMINAL_ACCEPTED" if accepted else "TERMINAL_REJECTED")).touch()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--workspace-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if project_root.name != "AgentEnhance" or project_root.is_symlink():
        raise SystemExit("project root must be a non-symlink AgentEnhance directory")
    uv = require_project_child(args.uv, project_root, "tools")
    output_root = require_project_child(args.output_root, project_root, "locks")
    evidence_root = require_project_child(args.evidence_root, project_root, "runs")
    workspace_manifest = args.workspace_manifest.resolve()
    if project_root not in workspace_manifest.parents or workspace_manifest.is_symlink():
        raise SystemExit("workspace manifest must be a regular project file")
    python = args.python.resolve()
    if not python.is_absolute() or python.is_symlink() or not python.is_file():
        raise SystemExit("Python interpreter must be an absolute regular file")
    if output_root.exists() or evidence_root.exists():
        raise SystemExit("refusing existing StructMem lock output or evidence root")
    output_root.mkdir(parents=True)
    evidence_root.mkdir(parents=True)
    started_at = now()
    record: dict[str, Any] = {
        "schema_version": "agentenhance.structmem_uv_lock_materialization.v1",
        "status": "RUNNING",
        "started_at": started_at,
    }
    try:
        import tomllib
        from pip._vendor.packaging.requirements import Requirement

        if workspace_manifest.stat().st_size != WORKSPACE_BYTES or sha256_file(workspace_manifest) != WORKSPACE_SHA256:
            raise RuntimeError("frozen StructMem workspace manifest identity mismatch")
        workspace = tomllib.loads(workspace_manifest.read_text(encoding="utf-8"))
        dependencies = workspace["project"]["dependencies"]
        requirements = [Requirement(row) for row in dependencies]
        names = [normalized_name(row.name) for row in requirements]
        if len(requirements) != EXPECTED_DIRECT_DEPENDENCIES or len(names) != len(set(names)):
            raise RuntimeError("StructMem direct dependency cardinality or uniqueness mismatch")
        if not all(str(row.specifier).startswith("==") for row in requirements):
            raise RuntimeError("StructMem direct dependency is not exact-pinned")
        if workspace["tool"]["uv"]["sources"]["torch"]["index"] != "pytorch-cpu":
            raise RuntimeError("Torch is not exclusively routed to the CPU registry")
        if sha256_file(uv) != UV_SHA256:
            raise RuntimeError("uv binary hash mismatch")
        uv_version = subprocess.check_output([str(uv), "--version"], text=True).strip()
        if uv_version != UV_VERSION_OUTPUT:
            raise RuntimeError(f"uv version mismatch: {uv_version}")
        if sha256_file(python) != PYTHON_SHA256:
            raise RuntimeError("Python interpreter hash mismatch")
        python_version = subprocess.check_output(
            [str(python), "-c", "import sys; print(sys.version)"], text=True
        ).strip()
        if not python_version.startswith(PYTHON_VERSION_PREFIX):
            raise RuntimeError(f"Python version mismatch: {python_version}")

        environment = dict(os.environ)
        environment.update(
            {
                "UV_HTTP_RETRIES": "0",
                "UV_HTTP_TIMEOUT": "60",
                "UV_CONCURRENT_DOWNLOADS": "1",
                "UV_CONCURRENT_BUILDS": "1",
                "UV_CONCURRENT_INSTALLS": "1",
                "UV_NO_PROGRESS": "1",
            }
        )
        lock_rows = []
        for label in ("a", "b"):
            workspace_root = output_root / label
            workspace_root.mkdir()
            shutil.copyfile(workspace_manifest, workspace_root / "pyproject.toml")
            completed = subprocess.run(
                lock_command(uv, python),
                cwd=workspace_root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=600,
                check=False,
            )
            log_path = evidence_root / f"uv-lock-{label}.log"
            log_path.write_text(completed.stdout, encoding="utf-8")
            if completed.returncode:
                raise RuntimeError(f"uv lock pass {label} failed with exit {completed.returncode}")
            lock = workspace_root / "uv.lock"
            if not lock.is_file():
                raise RuntimeError(f"uv lock pass {label} produced no lock")
            lock_rows.append(
                {"label": label, "path": str(lock), "bytes": lock.stat().st_size, "sha256": sha256_file(lock)}
            )
        if lock_rows[0]["sha256"] != lock_rows[1]["sha256"] or lock_rows[0]["bytes"] != lock_rows[1]["bytes"]:
            raise RuntimeError("independent StructMem lock passes are not byte-identical")

        record.update(
            {
                "status": "TERMINAL_ACCEPTED",
                "finished_at": now(),
                "upstream_pyproject_bytes": UPSTREAM_PYPROJECT_BYTES,
                "upstream_pyproject_sha256": UPSTREAM_PYPROJECT_SHA256,
                "workspace_manifest": str(workspace_manifest),
                "workspace_manifest_bytes": WORKSPACE_BYTES,
                "workspace_manifest_sha256": WORKSPACE_SHA256,
                "direct_dependency_count": len(requirements),
                "direct_dependency_names": sorted(names),
                "rank_bm25_resolution": "0.2.2",
                "torch_registry": "https://download.pytorch.org/whl/cpu",
                "uv": str(uv),
                "uv_sha256": UV_SHA256,
                "uv_version_output": uv_version,
                "python": str(python),
                "python_sha256": PYTHON_SHA256,
                "python_version": python_version,
                "network_retry_count": 0,
                "dependency_installations": 0,
                "lock_passes": lock_rows,
            }
        )
        seal(evidence_root, record, True)
        print(json.dumps({"status": record["status"], "direct_dependency_count": len(requirements), "lock_bytes": lock_rows[0]["bytes"], "lock_sha256": lock_rows[0]["sha256"], "network_retry_count": 0}, sort_keys=True))
        return 0
    except Exception as exc:
        record.update(
            {
                "status": "TERMINAL_REJECTED",
                "finished_at": now(),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "partial_output_retained": output_root.exists(),
                "cleanup_authorized": False,
            }
        )
        seal(evidence_root, record, False)
        print(json.dumps(record, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
