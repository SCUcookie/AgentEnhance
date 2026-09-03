#!/usr/bin/env python3
"""Export Hindsight's frozen uv.lock twice without resolving or installing."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


SOURCE_REVISION = "5e71494702bc050b6d58e783e6761f6c6cf3b74b"
LOCK_BYTES = 1_037_159
LOCK_SHA256 = "ce0966c58ac9018c77b8aa1d7d93fe9f405deb6c0fadb54e52608fe10a992063"
UV_SHA256 = "671793498fe0a545432e2524b6691ffb9eea4540d9fda43ca2f978df2dbf8426"
UV_VERSION_OUTPUT = "uv 0.12.9 (x86_64-unknown-linux-gnu)"
PYTHON_SHA256 = "db8630b1dda55498c4d254878d144e04d3c6fd82115b700c00a13c9029fdbd02"
PYTHON_VERSION_PREFIX = "3.11.0 | packaged by conda-forge |"
REQUIRED_PACKAGES = (
    "pg0-embedded==",
    "sentence-transformers==",
    "torch==2.10.0+cpu",
    "transformers==",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_project_path(path: Path, leaf: tuple[str, ...]) -> Path:
    path = path.resolve()
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"path must be absolute and not a symlink: {path}")
    parts = path.parts
    if not any(
        parts[index : index + len(leaf)] == leaf
        for index in range(len(parts) - len(leaf) + 1)
    ):
        raise ValueError(f"path is outside required scope {leaf}: {path}")
    return path


def requirement_heads(text: str) -> list[str]:
    return [
        line
        for line in text.splitlines()
        if line and not line[0].isspace() and not line.startswith(("#", "--"))
    ]


def export_command(uv: Path, python: Path, output: Path) -> list[str]:
    return [
        str(uv),
        "export",
        "--frozen",
        "--offline",
        "--no-cache",
        "--no-dev",
        "--package",
        "hindsight-all",
        "--no-emit-workspace",
        "--format",
        "requirements.txt",
        "--output-file",
        str(output),
        "--python",
        str(python),
        "--no-python-downloads",
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()

    uv = validate_project_path(args.uv, ("AgentEnhance", "tools"))
    source = validate_project_path(args.source, ("AgentEnhance", "third_party"))
    evidence_root = validate_project_path(args.evidence_root, ("AgentEnhance", "runs"))
    python = args.python.resolve()
    if not python.is_absolute() or python.is_symlink() or not python.is_file():
        raise SystemExit("Python interpreter must be an absolute regular file")
    if evidence_root.exists():
        raise SystemExit("refusing existing lock-export evidence root")
    evidence_root.mkdir(parents=True)
    started_at = now()
    try:
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
        revision = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip()
        if revision != SOURCE_REVISION:
            raise RuntimeError("Hindsight source revision mismatch")
        if subprocess.check_output(
            ["git", "-C", str(source), "status", "--porcelain"], text=True
        ).strip():
            raise RuntimeError("Hindsight source is dirty")
        lock = source / "uv.lock"
        if lock.stat().st_size != LOCK_BYTES or sha256_file(lock) != LOCK_SHA256:
            raise RuntimeError("Hindsight uv.lock identity mismatch")
        lock_before = sha256_file(lock)
        outputs = []
        environment = os.environ.copy()
        environment["UV_NO_PROGRESS"] = "1"
        for label in ("a", "b"):
            output = evidence_root / f"hindsight-all-requirements-{label}.txt"
            completed = subprocess.run(
                export_command(uv, python, output),
                cwd=source,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            (evidence_root / f"export-{label}.stdout.log").write_text(
                completed.stdout, encoding="utf-8"
            )
            (evidence_root / f"export-{label}.stderr.log").write_text(
                completed.stderr, encoding="utf-8"
            )
            outputs.append(output)
        lock_after = sha256_file(lock)
        if lock_after != lock_before:
            raise RuntimeError("uv.lock changed during frozen export")
        if subprocess.check_output(
            ["git", "-C", str(source), "status", "--porcelain"], text=True
        ).strip():
            raise RuntimeError("source changed during frozen export")
        if outputs[0].read_bytes() != outputs[1].read_bytes():
            raise RuntimeError("independent lock exports are not byte-identical")
        text = outputs[0].read_text(encoding="utf-8")
        prohibited = ("-e ", "file://", str(source), "hindsight-all @", "hindsight-api-slim @")
        if any(token in text for token in prohibited):
            raise RuntimeError("export contains a prohibited local workspace reference")
        if not all(token in text for token in REQUIRED_PACKAGES):
            raise RuntimeError("export is missing a required Hindsight runtime dependency")
        heads = requirement_heads(text)
        if not heads:
            raise RuntimeError("export contains no third-party requirements")
        result = {
            "schema_version": "agentenhance.hindsight_uv_lock_export.v1",
            "status": "TERMINAL_ACCEPTED",
            "source_revision": revision,
            "source": str(source),
            "uv_lock_bytes": lock.stat().st_size,
            "uv_lock_sha256_before": lock_before,
            "uv_lock_sha256_after": lock_after,
            "uv": str(uv),
            "uv_sha256": sha256_file(uv),
            "uv_version_output": uv_version,
            "python": str(python),
            "python_sha256": sha256_file(python),
            "python_version": python_version,
            "started_at": started_at,
            "finished_at": now(),
            "command": export_command(uv, python, Path("<OUTPUT>")),
            "exports": [
                {
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in outputs
            ],
            "byte_identical_exports": True,
            "requirement_head_count": len(heads),
            "requirement_heads": heads,
            "network_enabled": False,
            "dependency_install_performed": False,
        }
        record = evidence_root / "lock-export.json"
        record.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        evidence_files = [record, *outputs]
        evidence_files.extend(sorted(evidence_root.glob("export-*.log")))
        inventory = evidence_root / "EVIDENCE_SHA256SUMS"
        inventory.write_text(
            "".join(f"{sha256_file(path)}  {path}\n" for path in evidence_files),
            encoding="utf-8",
        )
        (evidence_root / "TERMINAL_ACCEPTED").touch()
        print(json.dumps({"status": result["status"], "requirement_head_count": len(heads), "export_bytes": outputs[0].stat().st_size, "export_sha256": sha256_file(outputs[0])}, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.hindsight_uv_lock_export_failure.v1",
            "status": "TERMINAL_REJECTED",
            "started_at": started_at,
            "finished_at": now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "cleanup_authorized": False,
        }
        record = evidence_root / "lock-export-failure.json"
        record.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (evidence_root / "EVIDENCE_SHA256SUMS").write_text(
            f"{sha256_file(record)}  {record}\n", encoding="utf-8"
        )
        (evidence_root / "TERMINAL_REJECTED").touch()
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
