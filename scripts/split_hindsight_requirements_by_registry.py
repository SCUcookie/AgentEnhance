#!/usr/bin/env python3
"""Split a frozen Hindsight requirements body by its package-level registry."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_hindsight_uv_lock as base  # noqa: E402


BODY_BYTES = 256_006
BODY_SHA256 = "6f0836431e1a0ba74bdc92732ffb0a81a1c72691bdab2bc3fba43c4a1e3716c6"
TOTAL_REQUIREMENTS = 208
PYPI_REQUIREMENTS = 206
PYTORCH_REQUIREMENTS = 2
PYPI_URL = "https://pypi.org/simple"
PYTORCH_URL = "https://download.pytorch.org/whl/cpu"


def requirement_blocks(payload: bytes) -> list[dict[str, object]]:
    lines = payload.splitlines(keepends=True)
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        decoded = line.decode("utf-8")
        if decoded and not decoded[0].isspace() and not decoded.startswith(("#", "--")):
            offsets.append(cursor)
        cursor += len(line)
    if not offsets or offsets[0] != 0:
        raise RuntimeError("dependency body does not begin with a requirement head")
    offsets.append(len(payload))
    blocks: list[dict[str, object]] = []
    for index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        block = payload[start:end]
        head = block.splitlines()[0].decode("utf-8")
        route = "pytorch-cpu" if head.startswith("torch==") else "pypi"
        blocks.append(
            {
                "sequence_index": index,
                "head": head,
                "route": route,
                "start_byte": start,
                "end_byte": end,
                "bytes": len(block),
                "sha256": base.hashlib.sha256(block).hexdigest(),
                "payload": block,
            }
        )
    return blocks


def split_payload(payload: bytes) -> tuple[bytes, bytes, list[dict[str, object]]]:
    blocks = requirement_blocks(payload)
    pypi = b"".join(row["payload"] for row in blocks if row["route"] == "pypi")
    pytorch = b"".join(row["payload"] for row in blocks if row["route"] == "pytorch-cpu")
    manifest = [{key: value for key, value in row.items() if key != "payload"} for row in blocks]
    reconstructed = b"".join(row["payload"] for row in blocks)
    if reconstructed != payload:
        raise RuntimeError("ordered route manifest does not reconstruct the dependency body")
    return pypi, pytorch, manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--body-reference", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    source = base.validate_project_path(args.source, ("AgentEnhance", "third_party"))
    body_reference = base.validate_project_path(args.body_reference, ("AgentEnhance", "runs"))
    evidence_root = base.validate_project_path(args.evidence_root, ("AgentEnhance", "runs"))
    if evidence_root.exists():
        raise SystemExit("refusing existing requirements-routing evidence root")
    evidence_root.mkdir(parents=True)
    started_at = base.now()
    try:
        revision = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip()
        if revision != base.SOURCE_REVISION:
            raise RuntimeError("Hindsight source revision mismatch")
        if subprocess.check_output(
            ["git", "-C", str(source), "status", "--porcelain"], text=True
        ).strip():
            raise RuntimeError("Hindsight source is dirty")
        lock = source / "uv.lock"
        if lock.stat().st_size != base.LOCK_BYTES or base.sha256_file(lock) != base.LOCK_SHA256:
            raise RuntimeError("Hindsight uv.lock identity mismatch")
        lock_text = lock.read_text(encoding="utf-8")
        registries = {
            line.split('registry = "', 1)[1].split('"', 1)[0]
            for line in lock_text.splitlines()
            if 'registry = "' in line
        }
        if registries != {PYPI_URL, PYTORCH_URL}:
            raise RuntimeError(f"unexpected uv.lock registry set: {sorted(registries)}")
        if (
            body_reference.stat().st_size != BODY_BYTES
            or base.sha256_file(body_reference) != BODY_SHA256
        ):
            raise RuntimeError("accepted dependency-body reference identity mismatch")
        payload = body_reference.read_bytes()
        first = split_payload(payload)
        second = split_payload(payload)
        if first != second:
            raise RuntimeError("independent registry splits are not identical")
        pypi, pytorch, routing = first
        if len(routing) != TOTAL_REQUIREMENTS:
            raise RuntimeError("total requirement cardinality mismatch")
        route_counts = {
            "pypi": sum(row["route"] == "pypi" for row in routing),
            "pytorch-cpu": sum(row["route"] == "pytorch-cpu" for row in routing),
        }
        if route_counts != {"pypi": PYPI_REQUIREMENTS, "pytorch-cpu": PYTORCH_REQUIREMENTS}:
            raise RuntimeError(f"registry route cardinality mismatch: {route_counts}")
        torch_heads = [row["head"] for row in routing if row["route"] == "pytorch-cpu"]
        if not all(str(head).startswith("torch==2.10.0") for head in torch_heads):
            raise RuntimeError(f"unexpected PyTorch-routed heads: {torch_heads}")
        pypi_path = evidence_root / "pypi-requirements.txt"
        pytorch_path = evidence_root / "pytorch-cpu-requirements.txt"
        pypi_path.write_bytes(pypi)
        pytorch_path.write_bytes(pytorch)
        routing_path = evidence_root / "registry-routing.json"
        routing_record = {
            "schema_version": "agentenhance.hindsight_registry_routing.v1",
            "status": "TERMINAL_ACCEPTED",
            "source_revision": revision,
            "uv_lock_bytes": lock.stat().st_size,
            "uv_lock_sha256": base.sha256_file(lock),
            "body_reference_bytes": len(payload),
            "body_reference_sha256": base.sha256_file(body_reference),
            "started_at": started_at,
            "finished_at": base.now(),
            "registries": {"pypi": PYPI_URL, "pytorch-cpu": PYTORCH_URL},
            "route_counts": route_counts,
            "ordered_blocks": routing,
            "outputs": {
                "pypi": {
                    "path": str(pypi_path),
                    "bytes": pypi_path.stat().st_size,
                    "sha256": base.sha256_file(pypi_path),
                },
                "pytorch-cpu": {
                    "path": str(pytorch_path),
                    "bytes": pytorch_path.stat().st_size,
                    "sha256": base.sha256_file(pytorch_path),
                },
            },
            "independent_splits_identical": True,
            "ordered_manifest_reconstructs_body": True,
            "network_enabled": False,
            "dependency_install_performed": False,
        }
        routing_path.write_text(
            json.dumps(routing_record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        evidence_files = [routing_path, pypi_path, pytorch_path]
        inventory = evidence_root / "EVIDENCE_SHA256SUMS"
        inventory.write_text(
            "".join(f"{base.sha256_file(path)}  {path}\n" for path in evidence_files),
            encoding="utf-8",
        )
        (evidence_root / "TERMINAL_ACCEPTED").touch()
        print(
            json.dumps(
                {
                    "status": "TERMINAL_ACCEPTED",
                    "route_counts": route_counts,
                    "pypi_sha256": base.sha256_file(pypi_path),
                    "pytorch_cpu_sha256": base.sha256_file(pytorch_path),
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.hindsight_registry_routing_failure.v1",
            "status": "TERMINAL_REJECTED",
            "started_at": started_at,
            "finished_at": base.now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "cleanup_authorized": False,
        }
        record = evidence_root / "registry-routing-failure.json"
        record.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (evidence_root / "EVIDENCE_SHA256SUMS").write_text(
            f"{base.sha256_file(record)}  {record}\n", encoding="utf-8"
        )
        (evidence_root / "TERMINAL_REJECTED").touch()
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
