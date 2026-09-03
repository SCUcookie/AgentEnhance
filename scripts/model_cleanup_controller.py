#!/usr/bin/env python3
"""Two-phase cleanup for exact project-owned, reproducibly archived model roots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ELIGIBLE_PREFIXES = (
    Path("/data1/2026/ldh/AgentEnhance/cache/models"),
    Path("/data2/2026/ldh/AgentEnhance/cache/models"),
)
RECORD_PREFIXES = (
    Path("/data1/2026/ldh/AgentEnhance/runs/model-cleanup"),
    Path("/data2/2026/ldh/AgentEnhance/runs/model-cleanup"),
)
BLOCK_BYTES = 8 * 1024 * 1024


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def has_unresolved_variable(value: str) -> bool:
    return "$" in value or "~" in value


def is_below(path: Path, prefix: Path) -> bool:
    try:
        path.relative_to(prefix)
    except ValueError:
        return False
    return path != prefix


def validate_exact_target(path: Path) -> None:
    if not path.is_absolute() or has_unresolved_variable(str(path)):
        raise RuntimeError("model target must be a literal absolute path")
    if not any(path.parent == prefix for prefix in ELIGIBLE_PREFIXES):
        raise RuntimeError("model target is not an exact child of an eligible model root")
    if path.is_symlink() or os.path.ismount(path):
        raise RuntimeError("model target is a symlink or mount point")
    if path.resolve() != path:
        raise RuntimeError("model target changes under path resolution")


def validate_record_path(path: Path) -> None:
    if not path.is_absolute() or has_unresolved_variable(str(path)):
        raise RuntimeError("cleanup record path must be literal and absolute")
    if not any(is_below(path, prefix) for prefix in RECORD_PREFIXES):
        raise RuntimeError("cleanup record path is outside the project record roots")
    if path.suffix != ".json":
        raise RuntimeError("cleanup record must be JSON")


def scan_tree(root: Path) -> dict[str, Any]:
    validate_exact_target(root)
    if not root.is_dir():
        raise RuntimeError(f"model root is not a directory: {root}")
    symlinks = sorted(path for path in root.rglob("*") if path.is_symlink())
    if symlinks:
        raise RuntimeError(f"model root contains symlinks: {symlinks[0]}")
    files = sorted(path for path in root.rglob("*") if path.is_file())
    tree = hashlib.sha256()
    total_bytes = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        total_bytes += size
        tree.update(relative.encode("utf-8"))
        tree.update(b"\0")
        tree.update(str(size).encode("ascii"))
        tree.update(b"\0")
        tree.update(sha256_file(path).encode("ascii"))
        tree.update(b"\n")
    stat = root.stat()
    return {
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "tree_sha256": tree.hexdigest(),
    }


def verify_inventory(root: Path, inventory: Path) -> str:
    if not root.is_dir() or not inventory.is_file():
        raise RuntimeError(f"missing retained evidence or inventory: {root}")
    for line in inventory.read_text(encoding="utf-8").splitlines():
        expected, raw_path = line.split(maxsplit=1)
        path = Path(raw_path.lstrip("*"))
        if not path.is_absolute():
            path = root / path
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"retained evidence inventory mismatch: {path}")
    return sha256_file(inventory)


def verify_model_inventory(
    inventory: Path, original_target: Path, current_target: Path
) -> dict[str, Any]:
    if not inventory.is_file():
        raise RuntimeError("model inventory is missing")
    expected_relatives: list[Path] = []
    expected_hashes: dict[Path, str] = {}
    for line in inventory.read_text(encoding="utf-8").splitlines():
        expected, raw_path = line.split(maxsplit=1)
        frozen_path = Path(raw_path.lstrip("*"))
        if not frozen_path.is_absolute():
            raise RuntimeError("model inventory paths must be absolute")
        try:
            relative = frozen_path.relative_to(original_target)
        except ValueError as error:
            raise RuntimeError("model inventory escapes the exact original target") from error
        if relative in expected_hashes:
            raise RuntimeError("duplicate model inventory path")
        expected_relatives.append(relative)
        expected_hashes[relative] = expected
    observed = sorted(
        path.relative_to(current_target)
        for path in current_target.rglob("*")
        if path.is_file()
    )
    if sorted(expected_relatives) != observed:
        raise RuntimeError("model inventory and on-disk file set differ")
    for relative, expected in expected_hashes.items():
        if sha256_file(current_target / relative) != expected:
            raise RuntimeError(f"model file hash mismatch: {relative}")
    return {
        "inventory_sha256": sha256_file(inventory),
        "file_count": len(observed),
    }


def validate_terminal_root(entry: dict[str, Any], label: str) -> Path:
    root = Path(entry["root"])
    inventory = Path(entry["inventory"])
    if not (root / "TERMINAL_ACCEPTED").is_file() or (root / "TERMINAL_REJECTED").exists():
        raise RuntimeError(f"{label} is not terminal-accepted: {root}")
    observed = verify_inventory(root, inventory)
    if observed != entry["inventory_sha256"]:
        raise RuntimeError(f"{label} inventory identity mismatch")
    return root


def validate_dependencies(
    eligibility: dict[str, Any], expected_dependents: set[str]
) -> list[Path]:
    entries = eligibility.get("dependent_evidence", [])
    observed = {entry.get("implementation_id") for entry in entries}
    if observed != expected_dependents or len(entries) != len(observed):
        raise RuntimeError("dependent evidence does not exactly cover the ownership ledger")
    retained: list[Path] = []
    for entry in entries:
        lifecycle = validate_terminal_root(entry["lifecycle"], "lifecycle evidence")
        summary = validate_terminal_root(entry["summary"], "three-seed summary")
        archive = validate_terminal_root(entry["archive"], "accepted evidence archive")
        payload = load_json(summary / "method-seed-summary.json")
        if (
            payload.get("implementation_id") != entry["implementation_id"]
            or payload.get("status") != "TERMINAL_ACCEPTED"
            or payload.get("main_comparison_eligible") is not True
            or payload.get("seed_count") != 3
            or payload.get("seeds") != [0, 1, 2]
            or payload.get("n_samples") != 150
            or payload.get("n_qa") != 7906
        ):
            raise RuntimeError("dependent three-seed summary is ineligible")
        retained.extend((lifecycle, summary, archive))
    return retained


def validate_repository_access(
    entry: dict[str, Any], repository: str, revision: str
) -> Path:
    path = Path(entry["path"])
    if not path.is_file() or sha256_file(path) != entry["sha256"]:
        raise RuntimeError("repository-access audit identity mismatch")
    payload = load_json(path)
    if (
        payload.get("status") != "IMMUTABLE_REVISION_ACCESSIBLE"
        or payload.get("repository") != repository
        or payload.get("revision") != revision
    ):
        raise RuntimeError("model repository is not audited as rematerializable")
    return path


def validate_no_process_references(target: Path) -> None:
    completed = subprocess.run(
        ["lsof", "-nP", "+D", str(target)],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode not in (0, 1):
        raise RuntimeError(f"lsof process audit failed: {completed.returncode}")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode == 0 or lines:
        raise RuntimeError(f"active process references model target: {target}")


def resolve_candidate(
    eligibility: dict[str, Any], ledger: dict[str, Any]
) -> tuple[dict[str, Any], set[str]]:
    model_id = eligibility.get("model_id")
    matches = [row for row in ledger["project_owned_candidates"] if row["model_id"] == model_id]
    if len(matches) != 1:
        raise RuntimeError("model is absent or duplicated in the ownership ledger")
    candidate = matches[0]
    if any(
        row["repository"] == candidate["repository"]
        and row["revision"] == candidate["revision"]
        for row in ledger["protected_shared_assets"]
    ):
        raise RuntimeError("protected shared model can never enter cleanup")
    expected_dependents = set(candidate["required_dependents"]) | set(
        candidate["conservative_endpoint_dependents"]
    )
    return candidate, expected_dependents


def validate_eligibility(
    path: Path, current_target: Path | None = None
) -> tuple[dict[str, Any], Path, Path, dict[str, Any], list[Path]]:
    eligibility = load_json(path)
    if eligibility.get("status") != "DRY_RUN_ELIGIBLE":
        raise RuntimeError("cleanup eligibility record is not DRY_RUN_ELIGIBLE")
    if any(has_unresolved_variable(str(value)) for value in eligibility.values() if isinstance(value, str)):
        raise RuntimeError("cleanup eligibility record contains an unresolved path variable")
    policy_entry = eligibility["policy"]
    ledger_entry = eligibility["ownership_ledger"]
    policy_path = Path(policy_entry["path"])
    ledger_path = Path(ledger_entry["path"])
    if sha256_file(policy_path) != policy_entry["sha256"]:
        raise RuntimeError("retention policy identity mismatch")
    if sha256_file(ledger_path) != ledger_entry["sha256"]:
        raise RuntimeError("ownership ledger identity mismatch")
    policy = load_json(policy_path)
    ledger = load_json(ledger_path)
    if policy.get("status") != "FROZEN_BEFORE_ANY_MODEL_CLEANUP":
        raise RuntimeError("retention policy is not frozen")
    candidate, expected_dependents = resolve_candidate(eligibility, ledger)
    target = Path(eligibility["target"])
    quarantine = Path(eligibility["quarantine"])
    validate_exact_target(target)
    validate_exact_target(quarantine)
    if quarantine.parent != target.parent or not quarantine.name.startswith(
        target.name + ".agentenhance-quarantine-"
    ):
        raise RuntimeError("quarantine is not an exact unique sibling of the model target")
    if candidate["repository"] != eligibility["repository"] or candidate["revision"] != eligibility[
        "revision"
    ]:
        raise RuntimeError("cleanup repository identity differs from the ledger")
    if not target.name == Path(candidate["target"]).name:
        raise RuntimeError("cleanup target differs from the ledger target")
    materialization = eligibility["materialization"]
    record_path = Path(materialization["record"])
    if sha256_file(record_path) != materialization["record_sha256"]:
        raise RuntimeError("model materialization record identity mismatch")
    record = load_json(record_path)
    if (
        record.get("status") != "TERMINAL_ACCEPTED"
        or record.get("repository") != candidate["repository"]
        or record.get("revision") != candidate["revision"]
        or record.get("target") != str(target)
        or record.get("file_count") != candidate["expected_files"]
        or record.get("total_bytes") != candidate["expected_bytes"]
    ):
        raise RuntimeError("model materialization record differs from the ledger")
    repository_audit = validate_repository_access(
        eligibility["repository_access_audit"], candidate["repository"], candidate["revision"]
    )
    retained = validate_dependencies(eligibility, expected_dependents)
    retained.extend((policy_path, ledger_path, record_path, repository_audit))
    current = current_target or target
    validate_exact_target(current)
    model_inventory = Path(materialization["model_inventory"])
    observed_inventory = verify_model_inventory(model_inventory, target, current)
    if observed_inventory["inventory_sha256"] != materialization["model_inventory_sha256"]:
        raise RuntimeError("model inventory identity mismatch")
    observed_shape = scan_tree(current)
    if observed_shape != eligibility["pre_cleanup"]:
        raise RuntimeError("live model shape differs from the dry-run eligibility record")
    validate_no_process_references(current)
    if eligibility.get("project_reference_audit") != "ONLY_RETIRED_ACCEPTED_DEPENDENTS":
        raise RuntimeError("project reference audit is not accepted")
    return eligibility, target, quarantine, observed_shape, retained


def write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    validate_record_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def preflight(record: Path) -> int:
    eligibility, target, quarantine, shape, retained = validate_eligibility(record)
    if quarantine.exists():
        raise RuntimeError("quarantine target already exists")
    print(
        json.dumps(
            {
                "status": "DRY_RUN_ELIGIBLE",
                "model_id": eligibility["model_id"],
                "target": str(target),
                "quarantine": str(quarantine),
                "pre_cleanup": shape,
                "retained_paths_verified": len(set(retained)),
                "mutation_performed": False,
            },
            sort_keys=True,
        )
    )
    return 0


def quarantine(record: Path, output: Path) -> int:
    eligibility, target, quarantine_path, shape, retained = validate_eligibility(record)
    validate_record_path(output)
    if output.exists() or quarantine_path.exists():
        raise RuntimeError("phase-1 output or quarantine target already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    os.rename(target, quarantine_path)
    if target.exists() or not quarantine_path.is_dir() or scan_tree(quarantine_path) != shape:
        raise RuntimeError("phase-1 quarantine postcondition failed")
    validate_no_process_references(quarantine_path)
    payload = {
        "schema_version": "agentenhance.model_cleanup_quarantine.v1",
        "status": "QUARANTINED",
        "created_at": now(),
        "model_id": eligibility["model_id"],
        "eligibility_record": str(record),
        "eligibility_record_sha256": sha256_file(record),
        "original_target": str(target),
        "quarantine": str(quarantine_path),
        "pre_cleanup": shape,
        "retained_paths_verified": sorted(str(path) for path in set(retained)),
        "original_absent": True,
        "quarantine_present": True,
        "deletion_performed": False,
    }
    write_json_exclusive(output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def delete_quarantine(record: Path, output: Path) -> int:
    phase1 = load_json(record)
    if phase1.get("status") != "QUARANTINED" or phase1.get("deletion_performed") is not False:
        raise RuntimeError("phase-1 record is not an undeleted quarantine")
    eligibility_path = Path(phase1["eligibility_record"])
    if sha256_file(eligibility_path) != phase1["eligibility_record_sha256"]:
        raise RuntimeError("phase-1 eligibility identity mismatch")
    eligibility, target, quarantine_path, shape, retained = validate_eligibility(
        eligibility_path, Path(phase1["quarantine"])
    )
    if (
        phase1["original_target"] != str(target)
        or phase1["quarantine"] != str(quarantine_path)
        or phase1["pre_cleanup"] != shape
        or target.exists()
    ):
        raise RuntimeError("phase-1 live state mismatch")
    validate_record_path(output)
    if output.exists():
        raise RuntimeError("phase-2 output record already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(quarantine_path)
    if target.exists() or quarantine_path.exists():
        raise RuntimeError("phase-2 deletion postcondition failed")
    validate_dependencies(
        eligibility,
        set(resolve_candidate(eligibility, load_json(Path(eligibility["ownership_ledger"]["path"])))[1]),
    )
    if not all(path.exists() for path in retained):
        raise RuntimeError("retained evidence disappeared after model deletion")
    payload = {
        "schema_version": "agentenhance.model_cleanup_deletion.v1",
        "status": "DELETED",
        "created_at": now(),
        "model_id": eligibility["model_id"],
        "phase1_record": str(record),
        "phase1_record_sha256": sha256_file(record),
        "original_target": str(target),
        "quarantine": str(quarantine_path),
        "deleted_file_count": shape["file_count"],
        "deleted_bytes": shape["total_bytes"],
        "original_absent": True,
        "quarantine_absent": True,
        "retained_paths_verified": len(set(retained)),
    }
    write_json_exclusive(output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("preflight", "quarantine", "delete"))
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--output-record", type=Path)
    args = parser.parse_args()
    if args.phase == "preflight":
        if args.output_record is not None:
            raise SystemExit("preflight does not write an output record")
        return preflight(args.record.resolve())
    if args.output_record is None:
        raise SystemExit("quarantine and delete require --output-record")
    output = args.output_record.resolve()
    if args.phase == "quarantine":
        return quarantine(args.record.resolve(), output)
    return delete_quarantine(args.record.resolve(), output)


if __name__ == "__main__":
    raise SystemExit(main())
