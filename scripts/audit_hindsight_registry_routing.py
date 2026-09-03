#!/usr/bin/env python3
"""Independently audit a retained Hindsight registry-routing evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


BODY_BYTES = 256_006
BODY_SHA256 = "6f0836431e1a0ba74bdc92732ffb0a81a1c72691bdab2bc3fba43c4a1e3716c6"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def audit(root: Path, body_reference: Path) -> dict[str, object]:
    if not (root / "TERMINAL_ACCEPTED").is_file():
        raise RuntimeError("TERMINAL_ACCEPTED is absent")
    if (root / "TERMINAL_REJECTED").exists():
        raise RuntimeError("TERMINAL_REJECTED is present")
    body = body_reference.read_bytes()
    if len(body) != BODY_BYTES or sha256_bytes(body) != BODY_SHA256:
        raise RuntimeError("accepted dependency-body reference identity mismatch")
    record_path = root / "registry-routing.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record["status"] != "TERMINAL_ACCEPTED":
        raise RuntimeError("routing record is not accepted")
    rows = record["ordered_blocks"]
    if len(rows) != 208:
        raise RuntimeError("ordered block count mismatch")
    cursor = 0
    routed: dict[str, list[bytes]] = {"pypi": [], "pytorch-cpu": []}
    for expected_index, row in enumerate(rows):
        if row["sequence_index"] != expected_index or row["start_byte"] != cursor:
            raise RuntimeError("ordered block sequence or byte continuity mismatch")
        end = row["end_byte"]
        if not isinstance(end, int) or end <= cursor or end > len(body):
            raise RuntimeError("invalid ordered block byte range")
        block = body[cursor:end]
        if len(block) != row["bytes"] or sha256_bytes(block) != row["sha256"]:
            raise RuntimeError("ordered block identity mismatch")
        route = row["route"]
        if route not in routed:
            raise RuntimeError(f"unexpected route: {route}")
        routed[route].append(block)
        cursor = end
    if cursor != len(body):
        raise RuntimeError("ordered blocks do not cover the full dependency body")
    route_files = {
        "pypi": root / "pypi-requirements.txt",
        "pytorch-cpu": root / "pytorch-cpu-requirements.txt",
    }
    route_hashes: dict[str, str] = {}
    for route, path in route_files.items():
        expected = b"".join(routed[route])
        if path.read_bytes() != expected:
            raise RuntimeError(f"{route} routed requirement file mismatch")
        route_hashes[route] = sha256_bytes(expected)
    if {key: len(value) for key, value in routed.items()} != {
        "pypi": 206,
        "pytorch-cpu": 2,
    }:
        raise RuntimeError("route cardinality mismatch")
    inventory_rows = []
    for line in (root / "EVIDENCE_SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected_sha, remote_path = line.split("  ", 1)
        local_path = root / Path(remote_path).name
        if sha256_bytes(local_path.read_bytes()) != expected_sha:
            raise RuntimeError(f"inventory mismatch: {local_path.name}")
        inventory_rows.append(local_path.name)
    if sorted(inventory_rows) != sorted(
        ["registry-routing.json", "pypi-requirements.txt", "pytorch-cpu-requirements.txt"]
    ):
        raise RuntimeError("unexpected evidence inventory membership")
    return {
        "status": "TERMINAL_ACCEPTED",
        "body_bytes": len(body),
        "body_sha256": sha256_bytes(body),
        "ordered_blocks_verified": len(rows),
        "route_counts": {key: len(value) for key, value in routed.items()},
        "route_hashes": route_hashes,
        "inventory_entries_verified": len(inventory_rows),
        "terminal_sentinels_consistent": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--body-reference", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.evidence_root, args.body_reference), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
