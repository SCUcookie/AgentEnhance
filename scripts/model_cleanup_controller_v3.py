#!/usr/bin/env python3
"""Ownership-v2-aware, three-track gate for project-owned model cleanup.

The controller keeps the proven low-level path, inventory, process, quarantine,
and deletion primitives from v1, but replaces its WMA-only dependency rule.  It
resolves the frozen v1 ownership base plus the v2 additive delta and requires a
terminal retirement receipt for every effective cross-track dependent.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping

import model_cleanup_controller as base
import model_cleanup_controller_v2 as cross_track


GLOBAL_COMPLETION_RECORD = cross_track.GLOBAL_COMPLETION_RECORD
POLICY_SHA256 = "196c83d19320f406b5ca4a1d124ef025d8dbf6672d9e538dd3d2795464dbfec7"
LEDGER_V1_SHA256 = "3b855e216f8eca4d39d18bade4bcdda91136df7d8a06333fcfd6d93067ff0613"
LEDGER_V2_SHA256 = "8ba9c463309b15b7ba087dae6882e43cab734f432d75dde3ec41dbfcaa922064"

TRACK_WMA = "wma-lifecycle-matched-v1"
TRACK_MEMGALLERY = "memgallery-static-matched-v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _contains_unresolved(value: Any) -> bool:
    if isinstance(value, str):
        return base.has_unresolved_variable(value)
    if isinstance(value, Mapping):
        return any(_contains_unresolved(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_unresolved(item) for item in value)
    return False


def _load_bound(entry: Mapping[str, Any], expected_sha256: str, label: str) -> tuple[Path, dict[str, Any]]:
    path = Path(str(entry.get("path", "")))
    _require(path.is_file(), f"missing {label}")
    observed = base.sha256_file(path)
    _require(entry.get("sha256") == expected_sha256 and observed == expected_sha256, f"{label} identity drift")
    return path, base.load_json(path)


def _dependent_key(raw: str) -> tuple[str, str]:
    if raw.startswith("memgallery-"):
        return TRACK_MEMGALLERY, raw[len("memgallery-") :]
    if raw.startswith("wma-"):
        return TRACK_WMA, raw
    raise RuntimeError(f"unregistered ownership dependent namespace: {raw}")


def resolve_effective_ownership(
    eligibility: Mapping[str, Any],
) -> tuple[dict[str, Any], set[tuple[str, str]], list[Path]]:
    v1_path, v1 = _load_bound(eligibility.get("ownership_ledger_v1", {}), LEDGER_V1_SHA256, "ownership ledger v1")
    v2_path, v2 = _load_bound(eligibility.get("ownership_ledger_v2", {}), LEDGER_V2_SHA256, "ownership ledger v2")
    _require(v1.get("schema_version") == "agentenhance.baseline_model_ownership_ledger.v1", "ownership ledger v1 schema drift")
    _require(v2.get("schema_version") == "agentenhance.baseline_model_ownership_ledger.v2", "ownership ledger v2 schema drift")
    _require(v2.get("supersedes", {}).get("sha256") == LEDGER_V1_SHA256, "ownership ledger inheritance drift")

    candidates = {row["model_id"]: dict(row) for row in v1.get("project_owned_candidates", [])}
    _require(len(candidates) == len(v1.get("project_owned_candidates", [])), "duplicate v1 ownership candidate")
    for delta in v2.get("expanded_project_owned_dependents", []):
        model_id = delta.get("model_id")
        _require(model_id in candidates, f"ownership delta has no v1 base: {model_id}")
        candidate = candidates[model_id]
        for field in ("repository", "revision", "target"):
            _require(delta.get(field) == candidate.get(field), f"ownership delta identity drift: {model_id}/{field}")
        inherited_required = delta.get("inherited_required_dependents", [])
        inherited_conservative = delta.get("inherited_conservative_endpoint_dependents", [])
        _require(inherited_required == candidate.get("required_dependents", []), f"required-dependent inheritance drift: {model_id}")
        _require(inherited_conservative == candidate.get("conservative_endpoint_dependents", []), f"conservative-dependent inheritance drift: {model_id}")
        candidate["required_dependents"] = inherited_required + list(delta.get("new_required_dependents", []))
    for addition in v2.get("new_project_owned_candidates", []):
        model_id = addition.get("model_id")
        _require(model_id not in candidates, f"duplicate additive ownership candidate: {model_id}")
        candidates[model_id] = dict(addition)

    model_id = eligibility.get("model_id")
    _require(model_id in candidates, "model is absent from the effective ownership ledger")
    candidate = candidates[model_id]
    protected = {
        (row.get("repository"), row.get("revision"))
        for row in v1.get("protected_shared_assets", [])
    }
    _require((candidate.get("repository"), candidate.get("revision")) not in protected, "protected shared model can never enter cleanup")
    raw_dependents = list(candidate.get("required_dependents", [])) + list(candidate.get("conservative_endpoint_dependents", []))
    dependents = {_dependent_key(raw) for raw in raw_dependents}
    _require(len(dependents) == len(raw_dependents), "duplicate effective ownership dependent")
    return candidate, dependents, [v1_path, v2_path]


def _signed_payload(entry: Mapping[str, Any], filename: str, label: str) -> tuple[Path, dict[str, Any]]:
    root = base.validate_terminal_root(dict(entry), label)
    payload_path = root / filename
    _require(payload_path.is_file() and not payload_path.is_symlink(), f"missing {label} payload")
    inventory = Path(str(entry["inventory"]))
    signed: set[Path] = set()
    for line in inventory.read_text(encoding="utf-8").splitlines():
        parts = line.split(maxsplit=1)
        _require(len(parts) == 2, f"malformed {label} inventory")
        path = Path(parts[1].lstrip("*"))
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as error:
            raise RuntimeError(f"{label} inventory escapes its root") from error
        signed.add(path)
    _require(payload_path.resolve() in signed, f"{label} payload is not inventory-signed")
    return root, base.load_json(payload_path)


def _global_context(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[Path]]:
    retained = cross_track.validate_global_completion(path)
    payload = base.load_json(path)
    tracks = {row["track_id"]: row for row in payload["tracks"]}
    return payload, tracks, retained


def validate_dependency_retirements(
    eligibility: Mapping[str, Any],
    expected: set[tuple[str, str]],
    completion_path: Path,
    tracks: Mapping[str, Mapping[str, Any]],
) -> list[Path]:
    entries = eligibility.get("dependent_retirements", [])
    _require(isinstance(entries, list), "dependent retirements must be a list")
    observed = {(row.get("track_id"), row.get("method_id")) for row in entries if isinstance(row, Mapping)}
    _require(len(entries) == len(observed) and observed == expected, "dependent retirements do not exactly cover effective ownership")
    completion_sha = base.sha256_file(completion_path)
    retained: list[Path] = []
    for entry in entries:
        track_id = str(entry["track_id"])
        method_id = str(entry["method_id"])
        track = tracks[track_id]
        root, payload = _signed_payload(entry["receipt"], "dependent-retirement.json", "dependent retirement")
        expected_outcome = "ACCEPTED" if method_id in track["accepted_methods"] else "TERMINAL_BLOCKED_OR_FAILED"
        _require(payload.get("schema_version") == "agentenhance.model_dependency_retirement.v1", "dependent retirement schema drift")
        _require(payload.get("status") == "TERMINAL_ACCEPTED_RETIRED", "dependent is not retired")
        _require((payload.get("track_id"), payload.get("method_id")) == (track_id, method_id), "dependent retirement identity drift")
        _require(payload.get("outcome") == expected_outcome, "dependent retirement outcome differs from global completion")
        _require(payload.get("global_completion_sha256") == completion_sha, "dependent retirement completion identity drift")
        _require(payload.get("track_archive") == track["archive"], "dependent retirement archive identity drift")
        _require(payload.get("official_values_used") is False, "dependent retirement used official values")
        _require(payload.get("pending_runs") == 0 and payload.get("active_process_references") == 0, "dependent still has active or pending work")
        _require(payload.get("model_reference_retired") is True, "dependent model reference is not retired")
        retained.append(root)
    return retained


def validate_project_reference_audit(
    eligibility: Mapping[str, Any],
    target: Path,
    dependents: set[tuple[str, str]],
    completion_path: Path,
) -> Path:
    root, payload = _signed_payload(eligibility.get("project_reference_audit", {}), "project-reference-audit.json", "project reference audit")
    expected_dependents = [
        {"track_id": track_id, "method_id": method_id}
        for track_id, method_id in sorted(dependents)
    ]
    _require(payload.get("status") == "TERMINAL_ACCEPTED_NO_ACTIVE_OR_PENDING_REFERENCES", "project reference audit is not accepted")
    _require(payload.get("model_id") == eligibility.get("model_id"), "project reference audit model drift")
    _require(payload.get("target") == str(target), "project reference audit target drift")
    _require(payload.get("global_completion_sha256") == base.sha256_file(completion_path), "project reference audit completion drift")
    _require(payload.get("registered_dependents") == expected_dependents, "project reference audit dependent drift")
    _require(payload.get("active_process_references") == [] and payload.get("pending_run_references") == [], "project reference audit found live references")
    _require(payload.get("datasets_results_logs_archives_retained") is True, "non-model retained paths were not protected")
    return root


def validate_eligibility(
    path: Path,
    current_target: Path | None = None,
    completion_path: Path | None = None,
) -> tuple[dict[str, Any], Path, Path, dict[str, Any], list[Path]]:
    eligibility = base.load_json(path)
    _require(eligibility.get("status") == "DRY_RUN_ELIGIBLE_V3", "cleanup eligibility record is not DRY_RUN_ELIGIBLE_V3")
    _require(not _contains_unresolved(eligibility), "cleanup eligibility record contains an unresolved path variable")
    policy_path, policy = _load_bound(eligibility.get("policy", {}), POLICY_SHA256, "retention policy")
    _require(policy.get("status") == "FROZEN_BEFORE_ANY_MODEL_CLEANUP", "retention policy is not frozen")
    candidate, dependents, ledger_paths = resolve_effective_ownership(eligibility)

    target = Path(eligibility["target"])
    quarantine_path = Path(eligibility["quarantine"])
    base.validate_exact_target(target)
    base.validate_exact_target(quarantine_path)
    _require(quarantine_path.parent == target.parent and quarantine_path.name.startswith(target.name + ".agentenhance-quarantine-"), "quarantine is not an exact unique sibling")
    for field in ("repository", "revision"):
        _require(eligibility.get(field) == candidate.get(field), f"cleanup {field} differs from effective ownership")
    _require(target.name == Path(candidate["target"]).name, "cleanup target differs from effective ownership")

    materialization = eligibility["materialization"]
    record_path = Path(materialization["record"])
    _require(record_path.is_file() and base.sha256_file(record_path) == materialization["record_sha256"], "model materialization record identity mismatch")
    record = base.load_json(record_path)
    _require(record.get("status") == "TERMINAL_ACCEPTED", "model materialization is not accepted")
    for field, expected in (("repository", candidate["repository"]), ("revision", candidate["revision"]), ("target", str(target)), ("file_count", candidate["expected_files"]), ("total_bytes", candidate["expected_bytes"])):
        _require(record.get(field) == expected, f"model materialization drift: {field}")
    repository_audit = base.validate_repository_access(eligibility["repository_access_audit"], candidate["repository"], candidate["revision"])

    completion = (completion_path or GLOBAL_COMPLETION_RECORD).resolve()
    _, tracks, global_retained = _global_context(completion)
    retirement_roots = validate_dependency_retirements(eligibility, dependents, completion, tracks)
    reference_root = validate_project_reference_audit(eligibility, target, dependents, completion)

    current = current_target or target
    base.validate_exact_target(current)
    model_inventory = Path(materialization["model_inventory"])
    observed_inventory = base.verify_model_inventory(model_inventory, target, current)
    _require(observed_inventory["inventory_sha256"] == materialization["model_inventory_sha256"], "model inventory identity mismatch")
    observed_shape = base.scan_tree(current)
    _require(observed_shape == eligibility.get("pre_cleanup"), "live model shape differs from dry-run eligibility")
    base.validate_no_process_references(current)
    retained = [policy_path, *ledger_paths, record_path, model_inventory, repository_audit, completion, *global_retained, *retirement_roots, reference_root]
    return eligibility, target, quarantine_path, observed_shape, list(dict.fromkeys(retained))


def preflight(record: Path) -> int:
    eligibility, target, quarantine_path, shape, retained = validate_eligibility(record)
    _require(not quarantine_path.exists(), "quarantine target already exists")
    print(json.dumps({"status": "DRY_RUN_ELIGIBLE_V3", "model_id": eligibility["model_id"], "target": str(target), "quarantine": str(quarantine_path), "pre_cleanup": shape, "retained_paths_verified": len(retained), "mutation_performed": False}, sort_keys=True))
    return 0


def _guarded_global(operation, *args):
    before = cross_track.validate_global_completion(GLOBAL_COMPLETION_RECORD)
    result = operation(*args)
    after = cross_track.validate_global_completion(GLOBAL_COMPLETION_RECORD)
    _require(set(before) == set(after), "cross-track retained-evidence roots changed during cleanup")
    return result


def _quarantine(record: Path, output: Path) -> int:
    eligibility, target, quarantine_path, shape, retained = validate_eligibility(record)
    base.validate_record_path(output)
    _require(not output.exists() and not quarantine_path.exists(), "phase-1 output or quarantine target already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    os.rename(target, quarantine_path)
    _require(not target.exists() and quarantine_path.is_dir() and base.scan_tree(quarantine_path) == shape, "phase-1 quarantine postcondition failed")
    base.validate_no_process_references(quarantine_path)
    payload = {
        "schema_version": "agentenhance.model_cleanup_quarantine.v3",
        "status": "QUARANTINED_V3",
        "created_at": base.now(),
        "model_id": eligibility["model_id"],
        "eligibility_record": str(record),
        "eligibility_record_sha256": base.sha256_file(record),
        "original_target": str(target),
        "quarantine": str(quarantine_path),
        "pre_cleanup": shape,
        "retained_paths_verified": sorted(str(item) for item in retained),
        "original_absent": True,
        "quarantine_present": True,
        "deletion_performed": False,
    }
    base.write_json_exclusive(output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def quarantine(record: Path, output: Path) -> int:
    return _guarded_global(_quarantine, record, output)


def _delete(record: Path, output: Path) -> int:
    phase1 = base.load_json(record)
    _require(phase1.get("status") == "QUARANTINED_V3" and phase1.get("deletion_performed") is False, "phase-1 record is not an undeleted v3 quarantine")
    eligibility_path = Path(phase1["eligibility_record"])
    _require(eligibility_path.is_file() and base.sha256_file(eligibility_path) == phase1["eligibility_record_sha256"], "phase-1 eligibility identity mismatch")
    eligibility, target, quarantine_path, shape, retained = validate_eligibility(eligibility_path, Path(phase1["quarantine"]))
    _require(phase1.get("original_target") == str(target) and phase1.get("quarantine") == str(quarantine_path), "phase-1 path identity drift")
    _require(phase1.get("pre_cleanup") == shape and phase1.get("retained_paths_verified") == sorted(str(item) for item in retained), "phase-1 evidence identity drift")
    _require(not target.exists(), "original target reappeared after quarantine")
    base.validate_record_path(output)
    _require(not output.exists(), "phase-2 output record already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(quarantine_path)
    _require(not target.exists() and not quarantine_path.exists(), "phase-2 deletion postcondition failed")
    _require(all(item.exists() for item in retained), "retained evidence disappeared after model deletion")
    payload = {
        "schema_version": "agentenhance.model_cleanup_deletion.v3",
        "status": "DELETED_V3",
        "created_at": base.now(),
        "model_id": eligibility["model_id"],
        "phase1_record": str(record),
        "phase1_record_sha256": base.sha256_file(record),
        "original_target": str(target),
        "quarantine": str(quarantine_path),
        "deleted_file_count": shape["file_count"],
        "deleted_bytes": shape["total_bytes"],
        "original_absent": True,
        "quarantine_absent": True,
        "retained_paths_verified": len(retained),
    }
    base.write_json_exclusive(output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def delete_quarantine(record: Path, output: Path) -> int:
    return _guarded_global(_delete, record, output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("preflight", "quarantine", "delete"))
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--output-record", type=Path)
    args = parser.parse_args()
    if args.phase == "preflight":
        _require(args.output_record is None, "preflight does not write an output record")
        return preflight(args.record.resolve())
    _require(args.output_record is not None, "quarantine and delete require --output-record")
    if args.phase == "quarantine":
        return quarantine(args.record.resolve(), args.output_record.resolve())
    return delete_quarantine(args.record.resolve(), args.output_record.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
