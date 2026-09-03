#!/usr/bin/env python3
"""Export Hindsight's frozen dependencies with their public index metadata."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_hindsight_uv_lock as v1  # noqa: E402


BODY_BYTES = 256_006
BODY_SHA256 = "6f0836431e1a0ba74bdc92732ffb0a81a1c72691bdab2bc3fba43c4a1e3716c6"
REQUIREMENT_HEAD_COUNT = 208
ALLOWED_INDEX_URLS = {
    "https://pypi.org/simple",
    "https://download.pytorch.org/whl/cpu",
}
ALLOWED_DIRECTIVES = ("--index-url ", "--extra-index-url ", "--find-links ")


def export_command(uv: Path, python: Path, output: Path) -> list[str]:
    command = v1.export_command(uv, python, output)
    output_index = command.index("--output-file")
    command[output_index:output_index] = [
        "--no-header",
        "--emit-index-url",
        "--emit-find-links",
    ]
    return command


def split_and_validate_export(payload: bytes, body: bytes) -> tuple[bytes, list[str]]:
    if not payload.endswith(body):
        raise RuntimeError("source-aware export does not preserve the accepted dependency body")
    prefix = payload[: -len(body)]
    if not prefix:
        raise RuntimeError("source-aware export contains no index metadata")
    directives = [line for line in prefix.decode("utf-8").splitlines() if line]
    urls: list[str] = []
    for line in directives:
        matching = [candidate for candidate in ALLOWED_DIRECTIVES if line.startswith(candidate)]
        if len(matching) != 1:
            raise RuntimeError(f"unexpected source directive: {line}")
        url = line[len(matching[0]) :]
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError(f"non-HTTPS source directive: {line}")
        if parsed.username or parsed.password:
            raise RuntimeError("credential-bearing source directive")
        urls.append(url.rstrip("/"))
    if set(urls) != ALLOWED_INDEX_URLS or len(urls) != len(ALLOWED_INDEX_URLS):
        raise RuntimeError(f"unexpected public index set: {urls}")
    return prefix, directives


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--body-reference", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()

    uv = v1.validate_project_path(args.uv, ("AgentEnhance", "tools"))
    source = v1.validate_project_path(args.source, ("AgentEnhance", "third_party"))
    body_reference = v1.validate_project_path(args.body_reference, ("AgentEnhance", "runs"))
    evidence_root = v1.validate_project_path(args.evidence_root, ("AgentEnhance", "runs"))
    python = args.python.resolve()
    if not python.is_absolute() or python.is_symlink() or not python.is_file():
        raise SystemExit("Python interpreter must be an absolute regular file")
    if evidence_root.exists():
        raise SystemExit("refusing existing source-aware export evidence root")
    evidence_root.mkdir(parents=True)
    started_at = v1.now()

    try:
        if v1.sha256_file(uv) != v1.UV_SHA256:
            raise RuntimeError("uv binary hash mismatch")
        uv_version = subprocess.check_output([str(uv), "--version"], text=True).strip()
        if uv_version != v1.UV_VERSION_OUTPUT:
            raise RuntimeError(f"uv version mismatch: {uv_version}")
        if v1.sha256_file(python) != v1.PYTHON_SHA256:
            raise RuntimeError("Python interpreter hash mismatch")
        python_version = subprocess.check_output(
            [str(python), "-c", "import sys; print(sys.version)"], text=True
        ).strip()
        if not python_version.startswith(v1.PYTHON_VERSION_PREFIX):
            raise RuntimeError(f"Python version mismatch: {python_version}")
        revision = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip()
        if revision != v1.SOURCE_REVISION:
            raise RuntimeError("Hindsight source revision mismatch")
        if subprocess.check_output(
            ["git", "-C", str(source), "status", "--porcelain"], text=True
        ).strip():
            raise RuntimeError("Hindsight source is dirty")
        lock = source / "uv.lock"
        if lock.stat().st_size != v1.LOCK_BYTES or v1.sha256_file(lock) != v1.LOCK_SHA256:
            raise RuntimeError("Hindsight uv.lock identity mismatch")
        if (
            body_reference.stat().st_size != BODY_BYTES
            or v1.sha256_file(body_reference) != BODY_SHA256
        ):
            raise RuntimeError("accepted dependency-body reference identity mismatch")
        body = body_reference.read_bytes()
        lock_before = v1.sha256_file(lock)
        outputs: list[Path] = []
        environment = os.environ.copy()
        environment["UV_NO_PROGRESS"] = "1"
        for label in ("a", "b"):
            output = evidence_root / f"hindsight-all-source-aware-{label}.txt"
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
        if v1.sha256_file(lock) != lock_before:
            raise RuntimeError("uv.lock changed during source-aware export")
        if subprocess.check_output(
            ["git", "-C", str(source), "status", "--porcelain"], text=True
        ).strip():
            raise RuntimeError("Hindsight source changed during source-aware export")
        payloads = [path.read_bytes() for path in outputs]
        if payloads[0] != payloads[1]:
            raise RuntimeError("independent source-aware exports are not byte-identical")
        prefix, directives = split_and_validate_export(payloads[0], body)
        text = payloads[0].decode("utf-8")
        if any(token in text for token in ("-e ", "file://", str(source), "hindsight-all @")):
            raise RuntimeError("source-aware export contains a prohibited workspace reference")
        heads = v1.requirement_heads(text)
        if len(heads) != REQUIREMENT_HEAD_COUNT:
            raise RuntimeError("source-aware requirement cardinality mismatch")
        canonical = evidence_root / "hindsight-all-source-aware-requirements.txt"
        canonical.write_bytes(payloads[0])
        result = {
            "schema_version": "agentenhance.hindsight_uv_source_aware_export.v1",
            "status": "TERMINAL_ACCEPTED",
            "source_revision": revision,
            "uv_lock_sha256_before": lock_before,
            "uv_lock_sha256_after": v1.sha256_file(lock),
            "uv_sha256": v1.sha256_file(uv),
            "uv_version_output": uv_version,
            "python_sha256": v1.sha256_file(python),
            "python_version": python_version,
            "body_reference_bytes": len(body),
            "body_reference_sha256": v1.sha256_file(body_reference),
            "started_at": started_at,
            "finished_at": v1.now(),
            "source_directives": directives,
            "source_directive_prefix_bytes": len(prefix),
            "canonical_export": {
                "path": str(canonical),
                "bytes": canonical.stat().st_size,
                "sha256": v1.sha256_file(canonical),
            },
            "byte_identical_exports": True,
            "dependency_body_byte_identical_to_accepted_reference": True,
            "requirement_head_count": len(heads),
            "network_enabled": False,
            "dependency_install_performed": False,
        }
        record = evidence_root / "source-aware-export.json"
        record.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        evidence_files = [record, canonical, *outputs]
        evidence_files.extend(sorted(evidence_root.glob("export-*.log")))
        inventory = evidence_root / "EVIDENCE_SHA256SUMS"
        inventory.write_text(
            "".join(f"{v1.sha256_file(path)}  {path}\n" for path in evidence_files),
            encoding="utf-8",
        )
        (evidence_root / "TERMINAL_ACCEPTED").touch()
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "source_directives": directives,
                    "export_bytes": canonical.stat().st_size,
                    "export_sha256": v1.sha256_file(canonical),
                    "requirement_head_count": len(heads),
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.hindsight_uv_source_aware_export_failure.v1",
            "status": "TERMINAL_REJECTED",
            "started_at": started_at,
            "finished_at": v1.now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "cleanup_authorized": False,
        }
        record = evidence_root / "source-aware-export-failure.json"
        record.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (evidence_root / "EVIDENCE_SHA256SUMS").write_text(
            f"{v1.sha256_file(record)}  {record}\n", encoding="utf-8"
        )
        (evidence_root / "TERMINAL_REJECTED").touch()
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
