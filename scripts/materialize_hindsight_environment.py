#!/usr/bin/env python3
"""Create an isolated Hindsight environment from an accepted offline wheelhouse."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PYTHON_SHA256 = "db8630b1dda55498c4d254878d144e04d3c6fd82115b700c00a13c9029fdbd02"
PYTHON_VERSION_PREFIX = "3.11.0 | packaged by conda-forge |"
ROUTES = {
    "pypi": {
        "requirements": "pypi-requirements.txt",
        "requirements_sha256": "76c279b04db08fe3c32fae4fc317d79e5fd9a8a21d3735e835700659b9310fef",
        "active": 198,
    },
    "pytorch-cpu": {
        "requirements": "pytorch-cpu-requirements.txt",
        "requirements_sha256": "7b91727207eb7d7c2198ea8ed687719cecd2d09af3e7194299def5774e531ba9",
        "active": 1,
    },
}
EXPECTED_ACTIVE = 199


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_name(value: str) -> str:
    return value.lower().replace("_", "-").replace(".", "-")


def require_project_child(path: Path, project_root: Path, component: str) -> Path:
    resolved = path.resolve()
    expected = (project_root / component).resolve()
    if resolved == expected or expected not in resolved.parents or resolved.is_symlink():
        raise ValueError(f"path is outside {component}: {resolved}")
    return resolved


def install_command(
    python: Path, routing_root: Path, wheelhouse_root: Path
) -> list[str]:
    return [
        str(python),
        "-m",
        "pip",
        "install",
        "--isolated",
        "--disable-pip-version-check",
        "--no-input",
        "--no-cache-dir",
        "--no-index",
        "--find-links",
        str(wheelhouse_root / "pypi"),
        "--find-links",
        str(wheelhouse_root / "pytorch-cpu"),
        "--no-deps",
        "--require-hashes",
        "--only-binary=:all:",
        "--requirement",
        str(routing_root / ROUTES["pypi"]["requirements"]),
        "--requirement",
        str(routing_root / ROUTES["pytorch-cpu"]["requirements"]),
    ]


def run_logged(command: list[str], log: Path, environment: dict[str, str]) -> None:
    started = time.monotonic()
    with log.open("w", encoding="utf-8") as handle:
        handle.write("COMMAND=" + json.dumps(command) + "\n")
        handle.flush()
        result = subprocess.run(
            command,
            env=environment,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        handle.write(f"\nEXIT_CODE={result.returncode}\n")
        handle.write(f"ELAPSED_SECONDS={time.monotonic() - started:.6f}\n")
    if result.returncode:
        raise RuntimeError(f"command failed with exit {result.returncode}: {command[:4]}")


def active_requirements(
    paths: list[Path], Requirement: Any, environment: dict[str, str]
) -> dict[str, Any]:
    active = {}
    for path in paths:
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw or raw[0].isspace() or raw.startswith(("#", "--")):
                continue
            requirement = Requirement(raw.removesuffix(chr(32) + chr(92)))
            if requirement.marker is not None and not requirement.marker.evaluate(environment):
                continue
            name = normalized_name(requirement.name)
            if name in active:
                raise RuntimeError(f"duplicate active requirement: {name}")
            active[name] = requirement
    return active


def verify_wheels(wheelhouse_root: Path, audit: dict[str, Any]) -> tuple[int, int]:
    expected = {(row["route"], row["file"]): row for row in audit.get("wheels", [])}
    observed = sorted(wheelhouse_root.glob("*/*"))
    if len(observed) != EXPECTED_ACTIVE or len(expected) != EXPECTED_ACTIVE:
        raise RuntimeError("accepted wheel inventory cardinality mismatch")
    total_bytes = 0
    for path in observed:
        key = (path.parent.name, path.name)
        row = expected.get(key)
        if (
            path.suffix != ".whl"
            or row is None
            or path.stat().st_size != row["bytes"]
            or sha256_file(path) != row["sha256"]
        ):
            raise RuntimeError(f"wheel no longer matches accepted audit: {path}")
        total_bytes += path.stat().st_size
    return len(observed), total_bytes


def seal(root: Path, record: dict[str, Any], accepted: bool) -> None:
    record_path = root / "environment-materialization.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    evidence = [
        path
        for path in sorted(root.iterdir())
        if path.is_file() and path.name not in {"SHA256SUMS", "TERMINAL_ACCEPTED", "TERMINAL_REJECTED"}
    ]
    (root / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in evidence),
        encoding="utf-8",
    )
    (root / ("TERMINAL_ACCEPTED" if accepted else "TERMINAL_REJECTED")).touch()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--routing-root", type=Path, required=True)
    parser.add_argument("--wheelhouse-root", type=Path, required=True)
    parser.add_argument("--wheelhouse-audit-record", type=Path, required=True)
    parser.add_argument("--wheelhouse-audit-record-sha256", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--environment-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if project_root.name != "AgentEnhance" or project_root.is_symlink():
        raise SystemExit("project root must be a non-symlink AgentEnhance directory")
    routing_root = require_project_child(args.routing_root, project_root, "runs")
    wheelhouse_root = require_project_child(args.wheelhouse_root, project_root, "wheelhouses")
    audit_record = require_project_child(args.wheelhouse_audit_record, project_root, "runs")
    source_root = require_project_child(args.source_root, project_root, "third_party")
    environment_root = require_project_child(args.environment_root, project_root, "environments")
    evidence_root = require_project_child(args.evidence_root, project_root, "runs")
    if environment_root.exists() or evidence_root.exists():
        raise SystemExit("refusing existing Hindsight environment or evidence root")
    evidence_root.mkdir(parents=True)
    started_at = now()
    record: dict[str, Any] = {
        "schema_version": "agentenhance.hindsight_environment_materialization.v1",
        "status": "RUNNING",
        "started_at": started_at,
        "environment_root": str(environment_root),
        "wheelhouse_root": str(wheelhouse_root),
        "source_root": str(source_root),
    }
    try:
        source_python = args.python.resolve()
        if (
            source_python.is_symlink()
            or not source_python.is_file()
            or sha256_file(source_python) != PYTHON_SHA256
        ):
            raise RuntimeError("source Python identity mismatch")
        version = subprocess.check_output(
            [str(source_python), "-c", "import sys; print(sys.version)"], text=True
        ).strip()
        if not version.startswith(PYTHON_VERSION_PREFIX):
            raise RuntimeError("source Python version mismatch")
        if sha256_file(audit_record) != args.wheelhouse_audit_record_sha256:
            raise RuntimeError("wheelhouse audit record identity mismatch")
        audit = json.loads(audit_record.read_text(encoding="utf-8"))
        if audit.get("status") != "TERMINAL_ACCEPTED" or audit.get("wheel_count") != EXPECTED_ACTIVE:
            raise RuntimeError("wheelhouse audit is not accepted")
        if not (audit_record.parent / "TERMINAL_ACCEPTED").is_file() or (
            audit_record.parent / "TERMINAL_REJECTED"
        ).exists():
            raise RuntimeError("wheelhouse audit terminal sentinels disagree")
        wheel_count, wheel_bytes = verify_wheels(wheelhouse_root, audit)

        from pip._vendor.packaging.markers import default_environment
        from pip._vendor.packaging.requirements import Requirement

        requirement_paths = []
        for route, contract in ROUTES.items():
            path = routing_root / contract["requirements"]
            if sha256_file(path) != contract["requirements_sha256"]:
                raise RuntimeError(f"{route} requirements identity mismatch")
            requirement_paths.append(path)
        requirements = active_requirements(
            requirement_paths, Requirement, default_environment()
        )
        if len(requirements) != EXPECTED_ACTIVE:
            raise RuntimeError("active requirement cardinality mismatch")

        environment = dict(os.environ)
        environment.update(
            {
                "PIP_CONFIG_FILE": os.devnull,
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_NO_INPUT": "1",
                "PIP_NO_INDEX": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "OMP_NUM_THREADS": "2",
                "MKL_NUM_THREADS": "2",
            }
        )
        run_logged(
            [str(source_python), "-m", "venv", "--copies", str(environment_root)],
            evidence_root / "venv-create.log",
            environment,
        )
        environment_python = environment_root / "bin" / "python"
        run_logged(
            install_command(environment_python, routing_root, wheelhouse_root),
            evidence_root / "pip-install.log",
            environment,
        )
        run_logged(
            [str(environment_python), "-m", "pip", "check"],
            evidence_root / "pip-check.log",
            environment,
        )
        source_paths = [
            source_root / "hindsight-all",
            source_root / "hindsight-api-slim",
            source_root / "hindsight-clients" / "python",
            source_root / "hindsight-embed",
        ]
        import_environment = dict(environment)
        import_environment["PYTHONPATH"] = os.pathsep.join(map(str, source_paths))
        import_code = (
            "import hindsight,hindsight_api,hindsight_client,hindsight_embed,pg0,torch;"
            "assert hasattr(hindsight,'HindsightServer');"
            "assert hasattr(hindsight,'HindsightClient');"
            "assert torch.isfinite(torch.tensor([1.0])).all();"
            "print('HINDSIGHT_IMPORT_OK')"
        )
        run_logged(
            [str(environment_python), "-c", import_code],
            evidence_root / "import-check.log",
            import_environment,
        )

        inventory_code = (
            "import importlib.metadata as m,json;"
            "print(json.dumps(sorted([{'name':d.metadata['Name'],'version':d.version} "
            "for d in m.distributions()],key=lambda x:x['name'].lower())))"
        )
        inventory_raw = subprocess.check_output(
            [str(environment_python), "-c", inventory_code],
            env=environment,
            text=True,
        )
        installed_rows = json.loads(inventory_raw)
        installed = {
            normalized_name(row["name"]): row["version"] for row in installed_rows
        }
        missing_or_wrong = {
            name: installed.get(name)
            for name, requirement in requirements.items()
            if name not in installed
            or not requirement.specifier.contains(installed[name], prereleases=True)
        }
        if missing_or_wrong:
            raise RuntimeError(f"installed distributions violate lock: {missing_or_wrong}")
        (evidence_root / "installed-distributions.json").write_text(
            json.dumps(installed_rows, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        freeze = subprocess.check_output(
            [str(environment_python), "-m", "pip", "freeze", "--all"],
            env=environment,
            text=True,
        )
        (evidence_root / "pip-freeze.txt").write_text(freeze, encoding="utf-8")
        record.update(
            {
                "status": "TERMINAL_ACCEPTED",
                "finished_at": now(),
                "source_python_sha256": PYTHON_SHA256,
                "source_python_version": version,
                "wheelhouse_audit_record_sha256": args.wheelhouse_audit_record_sha256,
                "wheel_count": wheel_count,
                "wheel_bytes": wheel_bytes,
                "active_locked_distributions": len(requirements),
                "installed_distribution_count": len(installed_rows),
                "offline_install": True,
                "source_install_performed": False,
                "model_load_performed": False,
                "network_access_performed": False,
                "gpu_load_performed": False,
            }
        )
        seal(evidence_root, record, True)
        print(json.dumps({k: record[k] for k in ("status", "wheel_count", "active_locked_distributions")}, sort_keys=True))
        return 0
    except Exception as exc:
        record.update(
            {
                "status": "TERMINAL_REJECTED",
                "finished_at": now(),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "partial_environment_retained": environment_root.exists(),
                "network_access_performed": False,
            }
        )
        seal(evidence_root, record, False)
        print(json.dumps(record, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
