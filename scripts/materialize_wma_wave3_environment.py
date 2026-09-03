#!/usr/bin/env python3
"""Materialize one isolated Wave-3 environment through a retained wheelhouse."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ALLOWED_METHODS = {"memoryos", "memgas"}
ROOT_PATTERN = re.compile(r"^/data[12]/[^/]+(?:/[^/]+)*/AgentEnhance$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_project_child(path: Path, project_root: Path, component: str) -> Path:
    resolved = path.resolve()
    expected_parent = (project_root / component).resolve()
    if resolved.parent != expected_parent or resolved.name in {"", ".", ".."}:
        raise RuntimeError(f"refusing path outside {expected_parent}: {resolved}")
    return resolved


def inventory(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": str(path.relative_to(root)),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(root.iterdir())
        if path.is_file()
    ]


def run_logged(
    command: list[str],
    *,
    log_path: Path,
    env: dict[str, str],
) -> None:
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write("COMMAND=" + json.dumps(command) + "\n")
        handle.flush()
        result = subprocess.run(
            command,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            check=False,
        )
        handle.write(f"\nEXIT_CODE={result.returncode}\n")
        handle.write(f"ELAPSED_SECONDS={time.monotonic() - started:.6f}\n")
    if result.returncode != 0:
        raise RuntimeError(f"command failed with {result.returncode}: {command[0:4]}")


def seal_evidence(evidence_root: Path, sentinel: str) -> None:
    rows = []
    for path in sorted(evidence_root.rglob("*")):
        if not path.is_file() or path.name in {
            "SHA256SUMS",
            "TERMINAL_ACCEPTED",
            "TERMINAL_REJECTED",
        }:
            continue
        rows.append(f"{sha256_file(path)}  {path.relative_to(evidence_root)}")
    (evidence_root / "SHA256SUMS").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (evidence_root / sentinel).touch()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=sorted(ALLOWED_METHODS), required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--environment-root", type=Path, required=True)
    parser.add_argument("--wheelhouse-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not ROOT_PATTERN.fullmatch(str(project_root)):
        raise SystemExit(f"refusing unexpected project root: {project_root}")
    environment_root = require_project_child(
        args.environment_root, project_root, "environments"
    )
    wheelhouse_root = require_project_child(
        args.wheelhouse_root, project_root, "wheelhouses"
    )
    evidence_root = require_project_child(args.evidence_root, project_root, "runs")
    for path in (environment_root, wheelhouse_root, evidence_root):
        if path.exists():
            raise SystemExit(f"refusing existing materialization root: {path}")

    source_python = args.python.resolve()
    requirements = args.requirements.resolve()
    if not source_python.is_file() or not os.access(source_python, os.X_OK):
        raise SystemExit(f"missing executable source Python: {source_python}")
    if not requirements.is_file():
        raise SystemExit(f"missing requirements file: {requirements}")

    version = subprocess.run(
        [str(source_python), "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not version.startswith("3.9."):
        raise SystemExit(f"Wave-3 environment requires Python 3.9, observed {version}")

    evidence_root.mkdir(parents=True)
    started_at = utc_now()
    record: dict[str, Any] = {
        "schema_version": "agentenhance.wma_wave3_environment_record.v1",
        "status": "RUNNING",
        "method": args.method,
        "started_at": started_at,
        "project_root": str(project_root),
        "source_python": str(source_python),
        "source_python_version": version,
        "requirements_path": str(requirements),
        "requirements_sha256": sha256_file(requirements),
        "materializer_sha256": sha256_file(Path(__file__).resolve()),
        "environment_root": str(environment_root),
        "wheelhouse_root": str(wheelhouse_root),
        "indexes": [
            "https://pypi.org/simple",
            "https://download.pytorch.org/whl/cpu",
        ],
    }
    record_path = evidence_root / "environment-record.json"
    environment = dict(os.environ)
    environment.update(
        {
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "OMP_NUM_THREADS": "2",
            "MKL_NUM_THREADS": "2",
        }
    )

    try:
        wheelhouse_root.mkdir(parents=True)
        run_logged(
            [str(source_python), "-m", "venv", str(environment_root)],
            log_path=evidence_root / "venv-create.log",
            env=environment,
        )
        python = environment_root / "bin" / "python"
        run_logged(
            [
                str(python),
                "-m",
                "pip",
                "wheel",
                "--no-cache-dir",
                "--retries",
                "0",
                "--timeout",
                "60",
                "--wheel-dir",
                str(wheelhouse_root),
                "--index-url",
                "https://pypi.org/simple",
                "--extra-index-url",
                "https://download.pytorch.org/whl/cpu",
                "--requirement",
                str(requirements),
            ],
            log_path=evidence_root / "pip-wheel.log",
            env=environment,
        )
        wheels = inventory(wheelhouse_root)
        if not wheels or any(not row["path"].endswith(".whl") for row in wheels):
            raise RuntimeError("wheelhouse is empty or contains a non-wheel artifact")
        run_logged(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--find-links",
                str(wheelhouse_root),
                "--requirement",
                str(requirements),
            ],
            log_path=evidence_root / "pip-install.log",
            env=environment,
        )
        run_logged(
            [str(python), "-m", "pip", "check"],
            log_path=evidence_root / "pip-check.log",
            env=environment,
        )
        if args.method == "memoryos":
            import_check = (
                "import faiss, numpy as np, openai, sentence_transformers, transformers; "
                "x=np.array([[1.0,0.0]],dtype='float32'); i=faiss.IndexFlatIP(2); "
                "i.add(x); d,n=i.search(x,1); assert n.tolist()==[[0]]; "
                "assert abs(float(d[0,0])-1.0)<1e-6"
            )
        else:
            import_check = (
                "import igraph, numpy, openai, sentence_transformers, sklearn, torch, transformers; "
                "assert hasattr(igraph, 'Graph'); assert torch.isfinite(torch.tensor([1.0])).all()"
            )
        run_logged(
            [str(python), "-c", import_check],
            log_path=evidence_root / "import-and-semantic-check.log",
            env=environment,
        )
        freeze = subprocess.run(
            [str(python), "-m", "pip", "freeze", "--all"],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout
        (evidence_root / "pip-freeze.txt").write_text(freeze, encoding="utf-8")
        record.update(
            {
                "status": "TERMINAL_ACCEPTED",
                "finished_at": utc_now(),
                "wheel_count": len(wheels),
                "wheel_bytes": sum(row["bytes"] for row in wheels),
                "wheel_inventory": wheels,
                "installed_distribution_count": len(
                    [line for line in freeze.splitlines() if line.strip()]
                ),
                "network_used_only_for_wheel_resolution": True,
                "offline_install_from_retained_wheelhouse": True,
                "gpu_loaded": False,
            }
        )
        record_path.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        seal_evidence(evidence_root, "TERMINAL_ACCEPTED")
        print(json.dumps(record, sort_keys=True))
        return 0
    except Exception as exc:
        record.update(
            {
                "status": "TERMINAL_REJECTED",
                "finished_at": utc_now(),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "partial_environment_retained": environment_root.exists(),
                "partial_wheelhouse_retained": wheelhouse_root.exists(),
            }
        )
        record_path.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        seal_evidence(evidence_root, "TERMINAL_REJECTED")
        print(json.dumps(record, sort_keys=True), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
