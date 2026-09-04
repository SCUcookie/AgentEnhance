#!/usr/bin/env python3
"""Load accepted Mem-Gallery data into answer-free, ordered run projections."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from audit_memgallery_dataset import git_blob_sha1, validate_manifest
from memgallery_control_adapter import adapt_scenario, validate_query_projection
from memgallery_lifecycle_controller import load_dataset_evidence, sha256_file


EXPECTED_REPOSITORY = "Ethan-Bei/Mem-Gallery"
EXPECTED_REVISION = "af912daba984e896e253016b7c7e334ef92c2a6f"
EXPECTED_SCENARIOS = 20
EXPECTED_QUESTIONS = 1711
EXPECTED_IMAGE_FILES = 1490


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _safe_dataset_file(dataset_root: Path, raw: object, prefix: tuple[str, ...]) -> Path:
    _require(isinstance(raw, str) and raw and "\\" not in raw and "\x00" not in raw, "invalid dataset path")
    relative = PurePosixPath(raw)
    _require(
        not relative.is_absolute()
        and relative.parts[: len(prefix)] == prefix
        and ".." not in relative.parts
        and "." not in relative.parts
        and all(relative.parts),
        f"unsafe dataset path: {raw!r}",
    )
    current = dataset_root
    for part in relative.parts:
        current = current / part
        _require(not current.is_symlink(), f"dataset path traverses a symlink: {raw}")
    _require(current.is_file(), f"dataset file is missing: {raw}")
    resolved = current.resolve(strict=True)
    _require(dataset_root == resolved.parent or dataset_root in resolved.parents, f"dataset path escapes root: {raw}")
    return resolved


def _manifest_by_path(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = validate_manifest(dict(manifest))
    return {str(row["path"]): row for row in rows}


def _verify_manifest_member(path: Path, row: Mapping[str, Any]) -> None:
    _require(path.stat().st_size == row.get("bytes"), f"manifest byte drift: {row.get('path')}")
    lfs = row.get("lfs_sha256")
    if lfs is not None:
        _require(sha256_file(path) == lfs, f"manifest LFS digest drift: {row.get('path')}")
    else:
        _require(git_blob_sha1(path, path.stat().st_size) == row.get("git_oid"), f"manifest Git blob drift: {row.get('path')}")


def _load_image_allowlist(
    *,
    dataset_root: Path,
    evidence_root: Path,
    manifest_rows: Mapping[str, Mapping[str, Any]],
    expected_image_files: int,
) -> dict[str, str]:
    references_path = evidence_root / "image-references.json"
    payload = json.loads(references_path.read_text(encoding="utf-8"))
    references = payload.get("references")
    referenced = payload.get("referenced_images")
    unreferenced = payload.get("unreferenced_images")
    _require(isinstance(references, list), "image reference rows are missing")
    _require(isinstance(referenced, list) and isinstance(unreferenced, list), "image partitions are missing")
    _require(referenced == sorted(set(referenced)), "referenced image partition is not unique and sorted")
    _require(unreferenced == sorted(set(unreferenced)), "unreferenced image partition is not unique and sorted")
    _require(not set(referenced) & set(unreferenced), "image partitions overlap")
    image_rows = {
        path: row for path, row in manifest_rows.items()
        if path.startswith("data/image/")
    }
    _require(len(image_rows) == expected_image_files, "manifest image denominator drift")
    _require(set(referenced) | set(unreferenced) == set(image_rows), "image partition differs from manifest")
    _require({row.get("resolved") for row in references} == set(referenced), "image references differ from partition")
    allowlist: dict[str, str] = {}
    for relative, row in sorted(image_rows.items()):
        digest = row.get("lfs_sha256")
        _require(isinstance(digest, str) and len(digest) == 64, f"image lacks frozen LFS SHA-256: {relative}")
        image_path = _safe_dataset_file(dataset_root, relative, ("data", "image"))
        _verify_manifest_member(image_path, row)
        allowlist[relative] = digest
    return allowlist


def _assert_answer_free(value: object, path: str = "projection") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            _require(key != "answer", f"raw answer key leaked at {path}")
            _assert_answer_free(child, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _assert_answer_free(child, f"{path}[{index}]")


def load_accepted_projections(
    *,
    dataset_root: Path,
    evidence_root: Path,
    source_manifest_path: Path,
    expected_scenarios: int = EXPECTED_SCENARIOS,
    expected_questions: int = EXPECTED_QUESTIONS,
    expected_image_files: int = EXPECTED_IMAGE_FILES,
) -> dict[str, Any]:
    """Revalidate accepted identities and return no-score, answer-free projections."""
    _require(dataset_root.is_absolute() and dataset_root.is_dir(), "dataset root must be absolute and present")
    _require(not dataset_root.is_symlink(), "dataset root must not be a symlink")
    dataset_root = dataset_root.resolve(strict=True)
    identity, question_rows, qids = load_dataset_evidence(evidence_root)
    _require(len(qids) == expected_questions, "accepted QID denominator drift")
    recorded_root = identity.get("dataset_root")
    _require(isinstance(recorded_root, str) and Path(recorded_root).resolve() == dataset_root, "dataset root differs from accepted evidence")
    _require(source_manifest_path.is_file() and not source_manifest_path.is_symlink(), "source manifest is missing or linked")
    _require(sha256_file(source_manifest_path) == identity.get("source_manifest_sha256"), "source manifest byte identity drift")
    manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    manifest_rows = _manifest_by_path(manifest)
    source = manifest.get("source", {})
    _require(source.get("repository") == EXPECTED_REPOSITORY, "dataset repository drift")
    _require(source.get("revision") == EXPECTED_REVISION, "dataset revision drift")
    stable = identity["stable_identity"]
    _require(stable.get("manifest_sha256") == hashlib.sha256(
        (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    ).hexdigest(), "canonical manifest identity drift")

    registered = identity.get("scenarios")
    _require(isinstance(registered, list) and len(registered) == expected_scenarios, "scenario denominator drift")
    scenario_names = [row.get("scenario") for row in registered]
    _require(
        all(isinstance(name, str) and name for name in scenario_names)
        and len(set(scenario_names)) == expected_scenarios,
        "scenario identities are missing or duplicated",
    )
    projections: list[dict[str, Any]] = []
    cursor = 0
    consumed_rounds = 0
    for scenario_row in registered:
        scenario = str(scenario_row["scenario"])
        relative = scenario_row.get("dialog_path")
        _require(isinstance(relative, str) and PurePosixPath(relative).stem == scenario, "scenario dialog identity drift")
        path = _safe_dataset_file(dataset_root, relative, ("data", "dialog"))
        _require(relative in manifest_rows, f"scenario dialog absent from source manifest: {relative}")
        _verify_manifest_member(path, manifest_rows[relative])
        payload = json.loads(path.read_text(encoding="utf-8"))
        _require(isinstance(payload, dict), f"scenario JSON is not an object: {relative}")
        projection = adapt_scenario(payload, scenario)
        questions = int(scenario_row.get("questions", -1))
        _require(len(projection["queries"]) == questions, f"scenario question denominator drift: {scenario}")
        _require(
            len(projection["memory_records"]) == scenario_row.get("runner_consumed_dialogue_rounds"),
            f"scenario consumed-round denominator drift: {scenario}",
        )
        frozen_slice = question_rows[cursor : cursor + questions]
        validate_query_projection(projection["queries"], frozen_slice)
        _assert_answer_free(projection)
        projections.append(projection)
        cursor += questions
        consumed_rounds += len(projection["memory_records"])
    _require(cursor == expected_questions, "projected question denominator drift")
    _require(
        [query["qid"] for projection in projections for query in projection["queries"]] == qids,
        "projected QID order drift",
    )
    _require(consumed_rounds == stable.get("runner_consumed_dialogue_rounds"), "projected memory denominator drift")
    allowlist = _load_image_allowlist(
        dataset_root=dataset_root,
        evidence_root=evidence_root,
        manifest_rows=manifest_rows,
        expected_image_files=expected_image_files,
    )
    return {
        "schema_version": "agentenhance.memgallery_projection_bundle.v1",
        "status": "ACCEPTED_ANSWER_FREE_PROJECTION",
        "dataset_semantic_identity_sha256": identity["dataset_semantic_identity_sha256"],
        "qid_order_sha256": stable["qid_order_sha256"],
        "question_index_sha256": stable["question_index_sha256"],
        "scenarios": projections,
        "question_rows": question_rows,
        "qids": qids,
        "allowed_image_sha256": allowlist,
        "scenario_count": len(projections),
        "question_count": len(qids),
        "memory_record_count": consumed_rounds,
        "image_count": len(allowlist),
        "raw_answers_returned": 0,
        "scores_observed": 0,
        "filesystem_mutations": 0,
    }
