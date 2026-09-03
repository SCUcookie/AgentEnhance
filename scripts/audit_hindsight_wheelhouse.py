#!/usr/bin/env python3
"""Independently audit a frozen Hindsight wheelhouse without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import sysconfig
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PYTHON_SHA256 = "db8630b1dda55498c4d254878d144e04d3c6fd82115b700c00a13c9029fdbd02"
PYTHON_VERSION_PREFIX = "3.11.0 | packaged by conda-forge |"
ROUTING_RECORD_SHA256 = "e0d1fd83c638af9db40c12029d017dd422ad141c9964a496e8cd398bb19b885e"
ROUTES = {
    "pypi": {
        "url": "https://pypi.org/simple",
        "requirements": "pypi-requirements.txt",
        "sha256": "76c279b04db08fe3c32fae4fc317d79e5fd9a8a21d3735e835700659b9310fef",
        "active": 198,
    },
    "pytorch-cpu": {
        "url": "https://download.pytorch.org/whl/cpu",
        "requirements": "pytorch-cpu-requirements.txt",
        "sha256": "7b91727207eb7d7c2198ea8ed687719cecd2d09af3e7194299def5774e531ba9",
        "active": 1,
    },
}
EXPECTED_WHEELS = 199
BYTE_CEILING = 6 * 1024**3


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


def requirement_blocks(
    path: Path, Requirement: Any, environment: dict[str, str]
) -> dict[str, dict[str, Any]]:
    blocks: list[tuple[Any, set[str]]] = []
    current = None
    hashes: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw and not raw[0].isspace() and not raw.startswith(("#", "--")):
            if current is not None:
                blocks.append((current, hashes))
            current = Requirement(raw.removesuffix(chr(32) + chr(92)))
            hashes = set()
            continue
        stripped = raw.strip().removesuffix(chr(32) + chr(92))
        if stripped.startswith("--hash=sha256:"):
            hashes.add(stripped.removeprefix("--hash=sha256:"))
    if current is not None:
        blocks.append((current, hashes))

    active: dict[str, dict[str, Any]] = {}
    for requirement, allowed_hashes in blocks:
        if requirement.marker is not None and not requirement.marker.evaluate(environment):
            continue
        name = normalized_name(requirement.name)
        if name in active or not allowed_hashes:
            raise RuntimeError(f"duplicate or hashless active requirement: {name}")
        active[name] = {
            "requirement": requirement,
            "hashes": allowed_hashes,
        }
    return active


def validate_download_commands(commands: list[list[str]]) -> None:
    if len(commands) != len(ROUTES):
        raise RuntimeError("wheelhouse materialization command cardinality mismatch")
    observed_routes = set()
    for command in commands:
        for flag in ("--isolated", "--no-cache-dir", "--no-deps", "--require-hashes", "--only-binary=:all:"):
            if flag not in command:
                raise RuntimeError(f"download command omitted {flag}")
        if "--extra-index-url" in command or command[command.index("--retries") + 1] != "0":
            raise RuntimeError("download command used an extra index or retry")
        index_url = command[command.index("--index-url") + 1]
        route = next((name for name, row in ROUTES.items() if row["url"] == index_url), None)
        if route is None or route in observed_routes:
            raise RuntimeError(f"unexpected or duplicate download route: {index_url}")
        observed_routes.add(route)
    if observed_routes != set(ROUTES):
        raise RuntimeError("download routes are incomplete")


def verify_evidence_inventory(path: Path) -> int:
    rows = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        digest, raw_path = raw.split(maxsplit=1)
        item = Path(raw_path.strip()).resolve()
        if not item.is_file() or sha256_file(item) != digest:
            raise RuntimeError(f"materialization evidence mismatch: {item}")
        rows += 1
    if rows == 0:
        raise RuntimeError("empty materialization evidence inventory")
    return rows


def seal(root: Path, record: dict[str, Any], accepted: bool) -> None:
    record_path = root / "wheelhouse-audit.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "SHA256SUMS").write_text(
        f"{sha256_file(record_path)}  {record_path.name}\n", encoding="utf-8"
    )
    (root / ("TERMINAL_ACCEPTED" if accepted else "TERMINAL_REJECTED")).touch()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--routing-root", type=Path, required=True)
    parser.add_argument("--wheelhouse-root", type=Path, required=True)
    parser.add_argument("--materialization-record", type=Path, required=True)
    parser.add_argument("--materialization-record-sha256", required=True)
    parser.add_argument("--audit-root", type=Path, required=True)
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if project_root.name != "AgentEnhance" or project_root.is_symlink():
        raise SystemExit("project root must be a non-symlink AgentEnhance directory")
    routing_root = require_project_child(args.routing_root, project_root, "runs")
    wheelhouse_root = require_project_child(args.wheelhouse_root, project_root, "wheelhouses")
    materialization_record = require_project_child(
        args.materialization_record, project_root, "runs"
    )
    audit_root = require_project_child(args.audit_root, project_root, "runs")
    if audit_root.exists():
        raise SystemExit("refusing existing wheelhouse audit root")
    audit_root.mkdir(parents=True)
    started_at = now()
    try:
        python = args.python.resolve()
        if python.is_symlink() or not python.is_file() or sha256_file(python) != PYTHON_SHA256:
            raise RuntimeError("Python interpreter identity mismatch")
        import subprocess

        version = subprocess.check_output(
            [str(python), "-c", "import sys; print(sys.version)"], text=True
        ).strip()
        if not version.startswith(PYTHON_VERSION_PREFIX):
            raise RuntimeError("Python version mismatch")
        from pip._vendor.packaging.markers import default_environment
        from pip._vendor.packaging.requirements import Requirement
        from pip._vendor.packaging.tags import sys_tags
        from pip._vendor.packaging.utils import parse_wheel_filename

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
            raise RuntimeError("audit interpreter platform/tag identity mismatch")

        routing_record = routing_root / "registry-routing.json"
        if sha256_file(routing_record) != ROUTING_RECORD_SHA256:
            raise RuntimeError("routing record identity mismatch")
        environment = default_environment()
        active_by_route = {}
        for route, contract in ROUTES.items():
            requirements = routing_root / contract["requirements"]
            if sha256_file(requirements) != contract["sha256"]:
                raise RuntimeError(f"{route} requirements identity mismatch")
            active = requirement_blocks(requirements, Requirement, environment)
            if len(active) != contract["active"]:
                raise RuntimeError(f"{route} active requirement cardinality mismatch")
            active_by_route[route] = active

        if sha256_file(materialization_record) != args.materialization_record_sha256:
            raise RuntimeError("materialization record identity mismatch")
        materialization = json.loads(materialization_record.read_text(encoding="utf-8"))
        if materialization.get("status") != "TERMINAL_ACCEPTED":
            raise RuntimeError("wheelhouse materialization is not accepted")
        if materialization.get("wheel_count") != EXPECTED_WHEELS:
            raise RuntimeError("materialization wheel count mismatch")
        if materialization.get("dependency_install_performed") is not False:
            raise RuntimeError("materialization unexpectedly installed dependencies")
        validate_download_commands(materialization.get("commands", []))
        materialization_root = materialization_record.parent
        if not (materialization_root / "TERMINAL_ACCEPTED").is_file() or (
            materialization_root / "TERMINAL_REJECTED"
        ).exists():
            raise RuntimeError("materialization terminal sentinels disagree")
        evidence_rows = verify_evidence_inventory(materialization_root / "EVIDENCE_SHA256SUMS")

        wheels = sorted(wheelhouse_root.glob("*/*"))
        if len(wheels) != EXPECTED_WHEELS or any(path.suffix != ".whl" for path in wheels):
            raise RuntimeError("wheelhouse count mismatch or non-wheel artifact")
        wheel_bytes = sum(path.stat().st_size for path in wheels)
        if wheel_bytes > BYTE_CEILING:
            raise RuntimeError("wheelhouse byte ceiling exceeded")
        recorded = {
            (row["route"], row["file"]): row for row in materialization.get("wheels", [])
        }
        observed_names = {route: set() for route in ROUTES}
        inventory = []
        for wheel in wheels:
            route = wheel.parent.name
            if route not in ROUTES:
                raise RuntimeError(f"unexpected wheel route: {route}")
            distribution, version_value, _build, wheel_tags = parse_wheel_filename(wheel.name)
            name = normalized_name(str(distribution))
            digest = sha256_file(wheel)
            requirement = active_by_route[route].get(name)
            if requirement is None or name in observed_names[route]:
                raise RuntimeError(f"unexpected or duplicate wheel distribution: {route}/{name}")
            if not wheel_tags.intersection(compatible_tags):
                raise RuntimeError(f"incompatible wheel: {wheel.name}")
            if not requirement["requirement"].specifier.contains(str(version_value), prereleases=True):
                raise RuntimeError(f"wheel version violates requirement: {wheel.name}")
            if digest not in requirement["hashes"]:
                raise RuntimeError(f"wheel digest absent from frozen requirement: {wheel.name}")
            row = {
                "route": route,
                "file": wheel.name,
                "distribution": name,
                "version": str(version_value),
                "bytes": wheel.stat().st_size,
                "sha256": digest,
            }
            if recorded.get((route, wheel.name)) != row:
                raise RuntimeError(f"wheel disagrees with materialization record: {wheel.name}")
            observed_names[route].add(name)
            inventory.append(row)
        if any(observed_names[route] != set(active_by_route[route]) for route in ROUTES):
            raise RuntimeError("wheel distributions do not equal active routed requirements")
        if len(recorded) != EXPECTED_WHEELS:
            raise RuntimeError("materialization wheel inventory cardinality mismatch")

        result = {
            "schema_version": "agentenhance.hindsight_wheelhouse_audit.v1",
            "status": "TERMINAL_ACCEPTED",
            "started_at": started_at,
            "finished_at": now(),
            "materialization_record_sha256": args.materialization_record_sha256,
            "routing_record_sha256": ROUTING_RECORD_SHA256,
            "active_requirement_counts": {
                route: len(rows) for route, rows in active_by_route.items()
            },
            "wheel_count": len(inventory),
            "wheel_bytes": wheel_bytes,
            "materialization_evidence_rows_verified": evidence_rows,
            "wheels": inventory,
            "network_access_performed": False,
            "dependency_install_performed": False,
        }
        seal(audit_root, result, True)
        print(json.dumps({k: result[k] for k in ("status", "wheel_count", "wheel_bytes")}, sort_keys=True))
        return 0
    except Exception as exc:
        result = {
            "schema_version": "agentenhance.hindsight_wheelhouse_audit_failure.v1",
            "status": "TERMINAL_REJECTED",
            "started_at": started_at,
            "finished_at": now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "wheelhouse_mutated": False,
        }
        seal(audit_root, result, False)
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
