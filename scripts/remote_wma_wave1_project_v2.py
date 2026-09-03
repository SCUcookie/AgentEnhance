#!/usr/bin/env python3
"""Project the accepted Wave-1 summaries into the frozen 30-row WMA tables."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


RUN_BASE = Path("/data1/2026/ldh/AgentEnhance/runs")
SUMMARY_ROOT = RUN_BASE / "wma-r1-wave1-three-seed-summaries-20260903-v1"
OUTPUT_ROOT = RUN_BASE / "wma-r1-wave1-table-projection-20260904-v2"
PROJECTED_ROOT = OUTPUT_ROOT / "projected-tables"
EXPECTED_IMPLEMENTATIONS = (
    "wma-mmfu-single",
    "wma-simplemem",
    "wma-m2a",
    "wma-vilomem",
)
OUTPUT_STORAGE_CEILING_BYTES = 100 * 1024**2
WALL_TIME_CEILING_SECONDS = 60 * 60

PACKAGE_FILES = {
    "scripts/project_wma_method_summaries.py": "4a61222b980c008e9588bf135828c51529c385dbf4f2b12e9730ad4d0a86eb73",
    "scripts/project_wma_method_summaries_v2.py": "c9a01b59ed3522b2aa3e7d1e5301f6b5dc183f0a2e08dea9de033a9cf200f1fa",
    "comparisons/wma-table-bundle-manifest.v3.json": "e7faa9d42e314b30d21542b90071bea4763014779b6674a00c234d7dc7d80914",
    "comparisons/wma-main-table-spec.v4.json": "f3a233b6e62419fa054557e18a326d7b2ba59210184bf782556dd1920f8c4937",
    "comparisons/wma-execution-matrix.v3.csv": "244759bf0eb55418fbdae0f840e913f4361d49ba9ba036ced99df84f20ce4331",
    "comparisons/wma-bibliographic-corrections.v1.json": "d6e36bd2617e354962bcf1b98a9d8b1d60bcadc559f08840f76df572c6b062a1",
    "comparisons/wma-main-table-template.v4.csv": "a549122d09839c9e4299118a95a85cf2f458ce08d7d66b1d915fdbf2836dafdf",
    "comparisons/wma-retrieval-memory-table-template.v3.csv": "afa675e72f01803640852505b1db22b9f6ff1f7ec0bedb228e42394946998108",
    "comparisons/wma-efficiency-reliability-table-template.v3.csv": "1eed37f9a6efccb1779154b5fc7ac1849efea0a80388d78f8fbef75600d3f098",
    "comparisons/wma-slice-table-template.v3.csv": "1239810e64178e1a1d46a655faf6e7b621c8acb3254fbca5bc496d2abb4feb63",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inventory(root: Path) -> str:
    inventory = root / "SHA256SUMS"
    if not inventory.is_file():
        raise RuntimeError(f"missing inventory: {inventory}")
    for line in inventory.read_text(encoding="utf-8").splitlines():
        expected, raw_path = line.split(maxsplit=1)
        path = Path(raw_path.lstrip("*"))
        if not path.is_absolute():
            path = root / path
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"inventory mismatch: {path}")
    return sha256_file(inventory)


def validate_package(package_root: Path) -> dict[str, str]:
    observed = {}
    for relative, expected in PACKAGE_FILES.items():
        path = package_root / relative
        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(f"control package identity mismatch: {relative}")
        observed[relative] = actual
    return observed


def validate_summary_root() -> tuple[str, dict[str, Any]]:
    if not (SUMMARY_ROOT / "TERMINAL_ACCEPTED").is_file() or (
        SUMMARY_ROOT / "TERMINAL_REJECTED"
    ).exists():
        raise RuntimeError("Wave-1 three-seed summary root is not terminal-accepted")
    inventory_sha256 = verify_inventory(SUMMARY_ROOT)
    manifest = json.loads((SUMMARY_ROOT / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "TERMINAL_ACCEPTED":
        raise RuntimeError("Wave-1 summary manifest is not terminal-accepted")
    children = manifest.get("children", {})
    if set(children) != set(EXPECTED_IMPLEMENTATIONS):
        raise RuntimeError("Wave-1 summary implementation set mismatch")
    for implementation_id in EXPECTED_IMPLEMENTATIONS:
        child = SUMMARY_ROOT / implementation_id
        if Path(children[implementation_id].get("root", "")) != child:
            raise RuntimeError(f"Wave-1 summary child path mismatch: {implementation_id}")
        child_inventory = verify_inventory(child)
        if child_inventory != children[implementation_id].get("inventory_sha256"):
            raise RuntimeError(f"Wave-1 summary child identity mismatch: {implementation_id}")
        aggregate_evidence = children[implementation_id].get("aggregate_evidence", [])
        if [row.get("seed") for row in aggregate_evidence] != [0, 1, 2]:
            raise RuntimeError(f"Wave-1 aggregate seed set mismatch: {implementation_id}")
        for row in aggregate_evidence:
            aggregate = Path(row["root"])
            if verify_inventory(aggregate) != row.get("inventory_sha256"):
                raise RuntimeError(f"Wave-1 aggregate identity mismatch: {aggregate}")
            audit = json.loads((aggregate / "audit.json").read_text(encoding="utf-8"))
            required = {
                "status": "TERMINAL_ACCEPTED",
                "main_comparison_eligible": True,
                "seed": row["seed"],
                "n_expected": 150,
                "n_observed": 150,
                "n_failed": 0,
                "n_qa": 7906,
            }
            for key, expected in required.items():
                if audit.get(key) != expected:
                    raise RuntimeError(f"Wave-1 aggregate audit mismatch: {aggregate}:{key}")
    return inventory_sha256, manifest


def write_inventory(root: Path) -> None:
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name not in {"SHA256SUMS", "TERMINAL_ACCEPTED", "TERMINAL_REJECTED"}
    )
    (root / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path}\n" for path in files),
        encoding="utf-8",
    )


def main() -> int:
    package_root = Path(__file__).resolve().parents[1]
    if OUTPUT_ROOT.exists():
        raise SystemExit(f"refusing existing projection root: {OUTPUT_ROOT}")
    package_identities = validate_package(package_root)
    summary_inventory_sha256, summary_manifest = validate_summary_root()
    OUTPUT_ROOT.mkdir(parents=True)
    try:
        command = [
            sys.executable,
            str(package_root / "scripts/project_wma_method_summaries_v2.py"),
            "--comparisons-root",
            str(package_root / "comparisons"),
        ]
        for implementation_id in EXPECTED_IMPLEMENTATIONS:
            command.extend(("--summary-root", str(SUMMARY_ROOT / implementation_id)))
        command.extend(("--output-root", str(PROJECTED_ROOT)))
        subprocess.run(command, check=True, timeout=WALL_TIME_CEILING_SECONDS)
        projected_inventory_sha256 = verify_inventory(PROJECTED_ROOT)
        projected = json.loads((PROJECTED_ROOT / "manifest.json").read_text(encoding="utf-8"))
        if projected.get("status") != "TERMINAL_ACCEPTED":
            raise RuntimeError("projected table bundle is not terminal-accepted")
        if projected.get("accepted_implementations") != sorted(EXPECTED_IMPLEMENTATIONS):
            raise RuntimeError("projected implementation set mismatch")
        if projected.get("official_values_used") is not False or projected.get(
            "blocked_or_proposed_values_used"
        ) is not False:
            raise RuntimeError("projected bundle imported disallowed values")
        expected_shapes = {
            "wma-main-table.csv": (30, 28),
            "wma-retrieval-memory-table.csv": (30, 28),
            "wma-efficiency-reliability-table.csv": (30, 38),
            "wma-slice-table.csv": (1590, 17),
        }
        for name, (rows, columns) in expected_shapes.items():
            observed = projected.get("files", {}).get(name, {})
            if observed.get("rows") != rows or observed.get("columns") != columns:
                raise RuntimeError(f"projected table shape mismatch: {name}")
        output_bytes = sum(path.stat().st_size for path in OUTPUT_ROOT.rglob("*") if path.is_file())
        if output_bytes > OUTPUT_STORAGE_CEILING_BYTES:
            raise RuntimeError(f"projection output exceeded 100 MiB ceiling: {output_bytes}")
        manifest = {
            "schema_version": "agentenhance.wma_wave1_table_projection.v2",
            "status": "TERMINAL_ACCEPTED",
            "selection": "none; exact frozen Wave-1 four-method set projected",
            "summary_root": str(SUMMARY_ROOT),
            "summary_root_inventory_sha256": summary_inventory_sha256,
            "summary_controller_inventory_sha256": summary_manifest.get(
                "controller_inventory_sha256"
            ),
            "accepted_implementations": sorted(EXPECTED_IMPLEMENTATIONS),
            "projected_root": str(PROJECTED_ROOT),
            "projected_inventory_sha256": projected_inventory_sha256,
            "package_file_sha256": package_identities,
            "official_values_used": False,
            "blocked_or_proposed_values_used": False,
            "claim_authorized": False,
            "next_gate": "archive raw Wave-1 evidence, then archive this projection and independently audit both",
        }
        (OUTPUT_ROOT / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        write_inventory(OUTPUT_ROOT)
        (OUTPUT_ROOT / "TERMINAL_ACCEPTED").touch()
    except Exception as exc:
        (OUTPUT_ROOT / "TERMINAL_REJECTED").write_text(
            json.dumps({"status": "TERMINAL_REJECTED", "error": repr(exc)}, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        raise
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
