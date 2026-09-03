#!/usr/bin/env python3
"""Recovery2: accept uv's exact target-qualified version output."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import materialize_uv_tool as base  # noqa: E402


EXPECTED_VERSION_OUTPUT = "uv 0.12.9 (x86_64-unknown-linux-gnu)"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--checksum-sidecar", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    archive = base.validate_path(args.archive, ("AgentEnhance", "incoming"))
    sidecar = base.validate_path(args.checksum_sidecar, ("AgentEnhance", "incoming"))
    target = base.validate_path(args.target, ("AgentEnhance", "tools"))
    evidence_root = base.validate_path(args.evidence_root, ("AgentEnhance", "runs"))
    if target.exists() or evidence_root.exists():
        raise SystemExit("refusing existing recovery2 target or evidence root")
    evidence_root.mkdir(parents=True)
    started_at = now()
    retained_archive = evidence_root / base.ARCHIVE_NAME
    retained_sidecar = evidence_root / f"{base.ARCHIVE_NAME}.sha256"
    try:
        if archive.stat().st_size != base.ARCHIVE_BYTES or sha256_file(archive) != base.ARCHIVE_SHA256:
            raise RuntimeError("staged archive identity mismatch")
        if sidecar.stat().st_size != base.CHECKSUM_BYTES or sha256_file(sidecar) != base.CHECKSUM_SHA256:
            raise RuntimeError("staged checksum identity mismatch")
        if sidecar.read_text(encoding="utf-8").strip().split() != [
            base.ARCHIVE_SHA256,
            base.ARCHIVE_NAME,
        ]:
            raise RuntimeError("staged checksum content mismatch")
        shutil.copyfile(archive, retained_archive)
        shutil.copyfile(sidecar, retained_sidecar)
        binaries = base.extract_binaries(retained_archive, target)
        if [row["path"] for row in binaries] != ["uv", "uvx"]:
            raise RuntimeError("expected exactly uv and uvx binaries")
        version = subprocess.check_output([str(target / "uv"), "--version"], text=True).strip()
        if version != EXPECTED_VERSION_OUTPUT:
            raise RuntimeError(f"uv version mismatch: {version}")
        result = {
            "schema_version": "agentenhance.uv_tool_staged_materialization.v2",
            "status": "TERMINAL_ACCEPTED",
            "recovery": "recovery2_exact_version_output",
            "version": base.VERSION,
            "target_triple": base.TARGET_TRIPLE,
            "target": str(target),
            "started_at": started_at,
            "finished_at": now(),
            "staged_archive": {"source": str(archive), "bytes": archive.stat().st_size, "sha256": sha256_file(archive)},
            "staged_checksum_sidecar": {"source": str(sidecar), "bytes": sidecar.stat().st_size, "sha256": sha256_file(sidecar)},
            "retained_archive_sha256": sha256_file(retained_archive),
            "retained_sidecar_sha256": sha256_file(retained_sidecar),
            "binaries": binaries,
            "version_output": version,
        }
        record = evidence_root / "uv-tool-materialization.json"
        record.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        inventory = evidence_root / "EVIDENCE_SHA256SUMS"
        inventory.write_text(
            f"{sha256_file(record)}  {record}\n"
            f"{sha256_file(retained_archive)}  {retained_archive}\n"
            f"{sha256_file(retained_sidecar)}  {retained_sidecar}\n",
            encoding="utf-8",
        )
        (evidence_root / "TERMINAL_ACCEPTED").touch()
        print(json.dumps({"status": result["status"], "recovery": result["recovery"], "version_output": version, "binary_count": len(binaries)}, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.uv_tool_staged_materialization_failure.v2",
            "status": "TERMINAL_REJECTED",
            "recovery": "recovery2_exact_version_output",
            "version": base.VERSION,
            "target": str(target),
            "started_at": started_at,
            "finished_at": now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "partial_target_retained": target.exists(),
            "cleanup_authorized": False,
        }
        record = evidence_root / "uv-tool-materialization-failure.json"
        record.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (evidence_root / "EVIDENCE_SHA256SUMS").write_text(
            f"{sha256_file(record)}  {record}\n", encoding="utf-8"
        )
        (evidence_root / "TERMINAL_REJECTED").touch()
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
