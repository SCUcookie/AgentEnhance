#!/usr/bin/env python3
"""Materialize a source-routed, hash-enforced Hindsight wheelhouse."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import sysconfig
from datetime import datetime, timezone
from pathlib import Path


PYTHON_SHA256 = "db8630b1dda55498c4d254878d144e04d3c6fd82115b700c00a13c9029fdbd02"
PYTHON_VERSION_PREFIX = "3.11.0 | packaged by conda-forge |"
PIP_VERSION = "22.3.1"
PIP_INIT_BYTES = 357
PIP_INIT_SHA256 = "67685719132f99d8699a6aabd0e5b57c0d898def2d9e6534bb389b468505fb0f"
ROUTING_RECORD_BYTES = 56_233
ROUTING_RECORD_SHA256 = "e0d1fd83c638af9db40c12029d017dd422ad141c9964a496e8cd398bb19b885e"
ROUTES = {
    "pypi": {
        "url": "https://pypi.org/simple",
        "requirements": "pypi-requirements.txt",
        "bytes": 251_961,
        "sha256": "76c279b04db08fe3c32fae4fc317d79e5fd9a8a21d3735e835700659b9310fef",
        "active_requirements": 198,
    },
    "pytorch-cpu": {
        "url": "https://download.pytorch.org/whl/cpu",
        "requirements": "pytorch-cpu-requirements.txt",
        "bytes": 4_045,
        "sha256": "7b91727207eb7d7c2198ea8ed687719cecd2d09af3e7194299def5774e531ba9",
        "active_requirements": 1,
    },
}
EXPECTED_ACTIVE_TOTAL = 199
BYTE_CEILING = 6 * 1024**3


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_project_child(path: Path, project_root: Path, child: str) -> Path:
    resolved = path.resolve()
    expected = (project_root / child).resolve()
    if resolved == expected or expected not in resolved.parents or resolved.is_symlink():
        raise ValueError(f"path is outside fresh {child} boundary: {resolved}")
    return resolved


def download_command(
    python: Path, requirements: Path, destination: Path, index_url: str
) -> list[str]:
    return [
        str(python),
        "-m",
        "pip",
        "download",
        "--isolated",
        "--disable-pip-version-check",
        "--no-input",
        "--no-cache-dir",
        "--progress-bar",
        "off",
        "--retries",
        "0",
        "--timeout",
        "60",
        "--no-deps",
        "--require-hashes",
        "--only-binary=:all:",
        "--index-url",
        index_url,
        "--dest",
        str(destination),
        "--requirement",
        str(requirements),
    ]


def active_requirements(path: Path, Requirement, environment: dict[str, str]) -> set[str]:
    heads = [
        line.removesuffix(" \\")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line[0].isspace() and not line.startswith(("#", "--"))
    ]
    active = set()
    for head in heads:
        requirement = Requirement(head)
        if requirement.marker is None or requirement.marker.evaluate(environment):
            active.add(requirement.name.lower().replace("_", "-").replace(".", "-"))
    return active


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--routing-root", type=Path, required=True)
    parser.add_argument("--wheelhouse-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if project_root.name != "AgentEnhance" or project_root.is_symlink():
        raise SystemExit("project root must be an absolute non-symlink AgentEnhance directory")
    python = args.python.resolve()
    routing_root = require_project_child(args.routing_root, project_root, "runs")
    wheelhouse_root = require_project_child(args.wheelhouse_root, project_root, "wheelhouses")
    evidence_root = require_project_child(args.evidence_root, project_root, "runs")
    if wheelhouse_root.exists() or evidence_root.exists():
        raise SystemExit("refusing existing wheelhouse or evidence root")
    evidence_root.mkdir(parents=True)
    started_at = now()
    try:
        if python.is_symlink() or not python.is_file() or sha256_file(python) != PYTHON_SHA256:
            raise RuntimeError("Python interpreter identity mismatch")
        python_version = subprocess.check_output(
            [str(python), "-c", "import sys; print(sys.version)"], text=True
        ).strip()
        if not python_version.startswith(PYTHON_VERSION_PREFIX):
            raise RuntimeError(f"Python version mismatch: {python_version}")
        import pip
        from pip._vendor.packaging.markers import default_environment
        from pip._vendor.packaging.requirements import Requirement
        from pip._vendor.packaging.tags import sys_tags
        from pip._vendor.packaging.utils import parse_wheel_filename

        pip_init = Path(pip.__file__).resolve()
        if (
            pip.__version__ != PIP_VERSION
            or pip_init.stat().st_size != PIP_INIT_BYTES
            or sha256_file(pip_init) != PIP_INIT_SHA256
        ):
            raise RuntimeError("pip identity mismatch")
        routing_record = routing_root / "registry-routing.json"
        if (
            routing_record.stat().st_size != ROUTING_RECORD_BYTES
            or sha256_file(routing_record) != ROUTING_RECORD_SHA256
        ):
            raise RuntimeError("registry-routing record identity mismatch")
        routing = json.loads(routing_record.read_text(encoding="utf-8"))
        if routing["status"] != "TERMINAL_ACCEPTED":
            raise RuntimeError("registry-routing record is not accepted")
        environment = default_environment()
        tags = list(sys_tags())
        compatible_tags = set(tags)
        if (
            sys.implementation.name != "cpython"
            or sysconfig.get_platform() != "linux-x86_64"
            or sysconfig.get_config_var("SOABI") != "cpython-311-x86_64-linux-gnu"
            or len(tags) != 788
            or str(tags[0]) != "cp311-cp311-manylinux_2_31_x86_64"
            or str(tags[-1]) != "py30-none-any"
        ):
            raise RuntimeError("target interpreter platform or tag identity mismatch")
        active_by_route: dict[str, set[str]] = {}
        for route, contract in ROUTES.items():
            requirements = routing_root / contract["requirements"]
            if (
                requirements.stat().st_size != contract["bytes"]
                or sha256_file(requirements) != contract["sha256"]
            ):
                raise RuntimeError(f"{route} requirements identity mismatch")
            active = active_requirements(requirements, Requirement, environment)
            if len(active) != contract["active_requirements"]:
                raise RuntimeError(f"{route} active requirement cardinality mismatch")
            active_by_route[route] = active
        if sum(map(len, active_by_route.values())) != EXPECTED_ACTIVE_TOTAL:
            raise RuntimeError("total active requirement cardinality mismatch")
        wheelhouse_root.mkdir(parents=True)
        environment_vars = os.environ.copy()
        environment_vars.update(
            {
                "PIP_CONFIG_FILE": os.devnull,
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        commands: list[list[str]] = []
        for route in ("pypi", "pytorch-cpu"):
            contract = ROUTES[route]
            destination = wheelhouse_root / route
            destination.mkdir()
            command = download_command(
                python,
                routing_root / contract["requirements"],
                destination,
                contract["url"],
            )
            completed = subprocess.run(
                command,
                env=environment_vars,
                text=True,
                capture_output=True,
                check=True,
            )
            (evidence_root / f"download-{route}.stdout.log").write_text(
                completed.stdout, encoding="utf-8"
            )
            (evidence_root / f"download-{route}.stderr.log").write_text(
                completed.stderr, encoding="utf-8"
            )
            commands.append(command)
        wheels = sorted(wheelhouse_root.glob("*/*"))
        if len(wheels) != EXPECTED_ACTIVE_TOTAL or any(path.suffix != ".whl" for path in wheels):
            raise RuntimeError("wheel count mismatch or non-wheel artifact present")
        if sum(path.stat().st_size for path in wheels) > BYTE_CEILING:
            raise RuntimeError("wheelhouse byte ceiling exceeded")
        observed_by_route: dict[str, set[str]] = {"pypi": set(), "pytorch-cpu": set()}
        wheel_inventory = []
        for wheel in wheels:
            distribution, version, _build, wheel_tags = parse_wheel_filename(wheel.name)
            route = wheel.parent.name
            normalized = str(distribution).lower().replace("_", "-").replace(".", "-")
            if route not in observed_by_route or not wheel_tags.intersection(compatible_tags):
                raise RuntimeError(f"unexpected route or incompatible wheel: {wheel}")
            if normalized in observed_by_route[route]:
                raise RuntimeError(f"duplicate wheel distribution in {route}: {normalized}")
            observed_by_route[route].add(normalized)
            wheel_inventory.append(
                {
                    "route": route,
                    "file": wheel.name,
                    "distribution": normalized,
                    "version": str(version),
                    "bytes": wheel.stat().st_size,
                    "sha256": sha256_file(wheel),
                }
            )
        if observed_by_route != active_by_route:
            raise RuntimeError("downloaded wheel distributions do not match active requirements")
        result = {
            "schema_version": "agentenhance.hindsight_wheelhouse.v1",
            "status": "TERMINAL_ACCEPTED",
            "started_at": started_at,
            "finished_at": now(),
            "python_sha256": sha256_file(python),
            "python_version": python_version,
            "pip_version": pip.__version__,
            "pip_init_sha256": sha256_file(pip_init),
            "platform": sysconfig.get_platform(),
            "soabi": sysconfig.get_config_var("SOABI"),
            "compatible_tag_count": len(tags),
            "first_compatible_tag": str(tags[0]),
            "last_compatible_tag": str(tags[-1]),
            "routing_record_sha256": sha256_file(routing_record),
            "commands": commands,
            "active_requirement_counts": {
                route: len(names) for route, names in active_by_route.items()
            },
            "wheel_count": len(wheels),
            "wheel_bytes": sum(path.stat().st_size for path in wheels),
            "wheels": wheel_inventory,
            "network_acquisition_performed": True,
            "dependency_install_performed": False,
            "source_routes_isolated": True,
            "hash_enforcement": True,
            "no_deps": True,
            "only_binary": True,
            "retry_count": 0,
        }
        record = evidence_root / "wheelhouse-materialization.json"
        record.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        evidence_files = [record, *sorted(evidence_root.glob("download-*.log")), *wheels]
        inventory = evidence_root / "EVIDENCE_SHA256SUMS"
        inventory.write_text(
            "".join(f"{sha256_file(path)}  {path}\n" for path in evidence_files),
            encoding="utf-8",
        )
        (evidence_root / "TERMINAL_ACCEPTED").touch()
        print(
            json.dumps(
                {
                    "status": "TERMINAL_ACCEPTED",
                    "wheel_count": len(wheels),
                    "wheel_bytes": result["wheel_bytes"],
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.hindsight_wheelhouse_failure.v1",
            "status": "TERMINAL_REJECTED",
            "started_at": started_at,
            "finished_at": now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "partial_wheelhouse_retained": wheelhouse_root.exists(),
            "cleanup_authorized": False,
        }
        record = evidence_root / "wheelhouse-materialization-failure.json"
        record.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        evidence_rows = [record, *sorted(evidence_root.glob("download-*.log"))]
        evidence_rows.extend(sorted(wheelhouse_root.glob("*/*")) if wheelhouse_root.exists() else [])
        (evidence_root / "EVIDENCE_SHA256SUMS").write_text(
            "".join(f"{sha256_file(path)}  {path}\n" for path in evidence_rows),
            encoding="utf-8",
        )
        (evidence_root / "TERMINAL_REJECTED").touch()
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
