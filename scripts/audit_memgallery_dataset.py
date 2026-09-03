#!/usr/bin/env python3
"""Audit a materialized Mem-Gallery snapshot before any numerical run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


BLOCK_BYTES = 8 * 1024 * 1024
IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
ALLOWED_DATASET_SCOPES = (
    Path("/data1/2026/ldh/AgentEnhance/datasets/raw"),
    Path("/data2/2026/ldh/AgentEnhance/datasets/raw"),
)
ALLOWED_RUN_SCOPES = (
    Path("/data1/2026/ldh/AgentEnhance/runs"),
    Path("/data2/2026/ldh/AgentEnhance/runs"),
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def git_blob_sha1(path: Path, size: int) -> str:
    digest = hashlib.sha1()
    digest.update(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative_path(raw: str, label: str) -> PurePosixPath:
    path = PurePosixPath(raw)
    if (
        not raw
        or "\\" in raw
        or "\x00" in raw
        or path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or any(not part for part in path.parts)
        or raw.endswith("/")
    ):
        raise ValueError(f"unsafe {label}: {raw!r}")
    return path


def validate_exact_child(path: Path, scopes: tuple[Path, ...], label: str) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{label} must be absolute and not a symlink: {path}")
    if not any(path.parent == scope and path.name for scope in scopes):
        raise ValueError(f"{label} must be an exact child of an allowed scope: {path}")


def validate_under_scope(path: Path, scopes: tuple[Path, ...], label: str) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{label} must be absolute and not a symlink: {path}")
    if not any(path == scope or scope in path.parents for scope in scopes):
        raise ValueError(f"{label} is outside allowed scopes: {path}")


def validate_manifest(payload: dict) -> list[dict]:
    if payload.get("status") != "FROZEN_BEFORE_DOWNLOAD":
        raise ValueError("dataset manifest is not frozen before download")
    source = payload.get("source", {})
    if source.get("repository") != "Ethan-Bei/Mem-Gallery":
        raise ValueError("unexpected dataset repository")
    revision = source.get("revision")
    if not isinstance(revision, str) or len(revision) != 40 or any(
        char not in "0123456789abcdef" for char in revision
    ):
        raise ValueError("dataset revision must be an immutable Git commit")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("dataset manifest has no files")
    paths = [str(item.get("path", "")) for item in files]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ValueError("dataset paths must be unique and sorted")
    for item in files:
        safe_relative_path(str(item["path"]), "manifest path")
        if not isinstance(item.get("bytes"), int) or item["bytes"] < 0:
            raise ValueError(f"invalid byte count for {item['path']}")
        oid = item.get("git_oid")
        if not isinstance(oid, str) or len(oid) != 40:
            raise ValueError(f"invalid Git oid for {item['path']}")
        lfs = item.get("lfs_sha256")
        if lfs is not None and (not isinstance(lfs, str) or len(lfs) != 64):
            raise ValueError(f"invalid LFS SHA-256 for {item['path']}")
    expected = payload.get("expected", {})
    if len(files) != expected.get("files") or sum(row["bytes"] for row in files) != expected.get(
        "bytes"
    ):
        raise ValueError("dataset manifest aggregate mismatch")
    return files


def resolve_image_reference(raw: str, kind: str) -> str:
    """Mirror the official runner while requiring every reference to remain in data/image."""
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise ValueError(f"invalid {kind} image reference: {raw!r}")
    if PurePosixPath(raw).is_absolute():
        raise ValueError(f"absolute {kind} image reference is prohibited: {raw!r}")
    if raw.startswith("../image/"):
        suffix = raw[len("../image/") :]
        relative = PurePosixPath("data/image") / safe_relative_path(suffix, f"{kind} image reference")
    elif kind == "conversation":
        relative = PurePosixPath("data") / safe_relative_path(raw, f"{kind} image reference")
    elif kind == "question":
        relative = PurePosixPath("data/image") / safe_relative_path(raw, f"{kind} image reference")
    else:
        raise ValueError(f"unknown image-reference kind: {kind}")
    if relative.parts[:2] != ("data", "image"):
        raise ValueError(f"{kind} image reference escapes data/image: {raw!r}")
    return relative.as_posix()


def _require_list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _validate_image_ref(
    raw: object,
    kind: str,
    image_paths: set[str],
    references: list[dict],
    owner: str,
    position: int,
) -> None:
    if not isinstance(raw, str):
        raise ValueError(f"{owner} image reference {position} must be a string")
    resolved = resolve_image_reference(raw, kind)
    if resolved not in image_paths:
        raise ValueError(f"{owner} references an image absent from the frozen manifest: {resolved}")
    references.append(
        {"owner": owner, "position": position, "kind": kind, "raw": raw, "resolved": resolved}
    )


def audit_dataset(dataset_root: Path, manifest: dict, expected_questions: int) -> dict:
    files = validate_manifest(manifest)
    if dataset_root.is_symlink() or not dataset_root.is_dir():
        raise ValueError(f"dataset root must be an existing non-symlink directory: {dataset_root}")

    expected_paths = [str(row["path"]) for row in files]
    observed_paths: list[str] = []
    for path in dataset_root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"dataset contains a symlink: {path}")
        if path.is_file():
            observed_paths.append(path.relative_to(dataset_root).as_posix())
        elif not path.is_dir():
            raise ValueError(f"dataset contains a non-regular entry: {path}")
    observed_paths.sort()
    if observed_paths != expected_paths:
        missing = sorted(set(expected_paths) - set(observed_paths))[:5]
        extra = sorted(set(observed_paths) - set(expected_paths))[:5]
        raise ValueError(f"dataset path inventory mismatch: missing={missing}, extra={extra}")

    verified_files: list[dict] = []
    for row in files:
        path = dataset_root.joinpath(*PurePosixPath(row["path"]).parts)
        size = path.stat().st_size
        if size != row["bytes"]:
            raise ValueError(f"byte mismatch for {row['path']}: {size} != {row['bytes']}")
        observed_sha256 = sha256_file(path)
        if "lfs_sha256" in row:
            if observed_sha256 != row["lfs_sha256"]:
                raise ValueError(f"LFS SHA-256 mismatch for {row['path']}")
            identity_type = "lfs-sha256"
            frozen_identity = row["lfs_sha256"]
        else:
            observed_git_blob = git_blob_sha1(path, size)
            if observed_git_blob != row["git_oid"]:
                raise ValueError(f"Git blob SHA-1 mismatch for {row['path']}")
            identity_type = "git-blob-sha1"
            frozen_identity = row["git_oid"]
        verified_files.append(
            {
                "path": row["path"],
                "bytes": size,
                "sha256": observed_sha256,
                "frozen_identity_type": identity_type,
                "frozen_identity": frozen_identity,
            }
        )

    image_paths = {
        row["path"]
        for row in files
        if row["path"].startswith("data/image/")
        and PurePosixPath(row["path"]).suffix.lower() in IMAGE_SUFFIXES
    }
    dialog_paths = [
        row["path"]
        for row in files
        if row["path"].startswith("data/dialog/") and row["path"].endswith(".json")
    ]
    question_rows: list[dict] = []
    image_references: list[dict] = []
    scenarios: list[dict] = []
    total_sessions = 0
    total_dialogue_rounds = 0
    runner_consumed_dialogue_rounds = 0

    for relative in dialog_paths:
        dialog_path = dataset_root.joinpath(*PurePosixPath(relative).parts)
        try:
            payload = json.loads(dialog_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid UTF-8 JSON in {relative}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"dialog file must contain an object: {relative}")
        stem = PurePosixPath(relative).stem
        conversations = _require_list(payload.get("multi_session_dialogues"), f"{relative} dialogues")
        qas = _require_list(payload.get("human-annotated QAs"), f"{relative} QAs")
        profile = payload.get("character_profile", {})
        if not isinstance(profile, dict):
            raise ValueError(f"{relative} character_profile must be an object")

        scenario_rounds = 0
        scenario_consumed = 0
        for session_index, session in enumerate(conversations):
            if not isinstance(session, dict):
                raise ValueError(f"{relative} session {session_index} must be an object")
            dialogues = _require_list(
                session.get("dialogues"), f"{relative} session {session_index} dialogues"
            )
            total_sessions += 1
            for round_index, dialogue in enumerate(dialogues):
                if not isinstance(dialogue, dict):
                    raise ValueError(
                        f"{relative} session {session_index} round {round_index} must be an object"
                    )
                scenario_rounds += 1
                total_dialogue_rounds += 1
                user = dialogue.get("user", "")
                assistant = dialogue.get("assistant", "")
                if not isinstance(user, str) or not isinstance(assistant, str):
                    raise ValueError(f"{relative} dialogue text fields must be strings")
                if user or assistant:
                    scenario_consumed += 1
                    runner_consumed_dialogue_rounds += 1
                if "input_image" in dialogue:
                    images = _require_list(
                        dialogue["input_image"],
                        f"{relative} session {session_index} round {round_index} input_image",
                    )
                    for image_index, raw in enumerate(images):
                        _validate_image_ref(
                            raw,
                            "conversation",
                            image_paths,
                            image_references,
                            f"{stem}:session-{session_index}:round-{round_index}",
                            image_index,
                        )
                    for field in ("image_caption", "image_id"):
                        if field in dialogue and not isinstance(dialogue[field], list):
                            raise ValueError(f"{relative} dialogue {field} must be a list")

        for qa_index, qa in enumerate(qas):
            if not isinstance(qa, dict):
                raise ValueError(f"{relative} QA {qa_index} must be an object")
            question = qa.get("question")
            answer = qa.get("answer")
            if not isinstance(question, str) or not question.strip():
                raise ValueError(f"{relative} QA {qa_index} has an empty/non-string question")
            if not isinstance(answer, str):
                raise ValueError(f"{relative} QA {qa_index} answer must be a string")
            if "clue" in qa and not isinstance(qa["clue"], list):
                raise ValueError(f"{relative} QA {qa_index} clue must be a list")
            qid = f"{stem}:{qa_index}"
            if qa.get("question_image"):
                _validate_image_ref(
                    qa["question_image"],
                    "question",
                    image_paths,
                    image_references,
                    qid,
                    0,
                )
            question_rows.append(
                {
                    "qid": qid,
                    "dialog_path": relative,
                    "scenario": stem,
                    "qa_index": qa_index,
                    "question_sha256": sha256_bytes(question.encode("utf-8")),
                    "answer_sha256": sha256_bytes(answer.encode("utf-8")),
                    "qa_canonical_sha256": sha256_bytes(canonical_json_bytes(qa)),
                    "category": qa.get("point", ""),
                    "has_question_image": bool(qa.get("question_image")),
                }
            )
        scenarios.append(
            {
                "scenario": stem,
                "dialog_path": relative,
                "sessions": len(conversations),
                "dialogue_rounds": scenario_rounds,
                "runner_consumed_dialogue_rounds": scenario_consumed,
                "questions": len(qas),
            }
        )

    qids = [row["qid"] for row in question_rows]
    if len(qids) != len(set(qids)):
        raise ValueError("question IDs are not unique")
    if len(qids) != expected_questions:
        raise ValueError(f"question denominator mismatch: {len(qids)} != {expected_questions}")
    qid_bytes = "".join(f"{qid}\n" for qid in qids).encode("utf-8")
    question_index_bytes = b"".join(canonical_json_bytes(row) for row in question_rows)
    referenced_images = sorted({row["resolved"] for row in image_references})
    unreferenced_images = sorted(image_paths - set(referenced_images))
    stable_identity = {
        "repository": manifest["source"]["repository"],
        "revision": manifest["source"]["revision"],
        "manifest_sha256": sha256_bytes(canonical_json_bytes(manifest)),
        "files": len(files),
        "bytes": sum(row["bytes"] for row in files),
        "dialog_files": len(dialog_paths),
        "image_files": len(image_paths),
        "sessions": total_sessions,
        "dialogue_rounds": total_dialogue_rounds,
        "runner_consumed_dialogue_rounds": runner_consumed_dialogue_rounds,
        "questions": len(qids),
        "qid_order_sha256": sha256_bytes(qid_bytes),
        "question_index_sha256": sha256_bytes(question_index_bytes),
        "referenced_images": len(referenced_images),
        "unreferenced_images": len(unreferenced_images),
    }
    return {
        "stable_identity": stable_identity,
        "dataset_semantic_identity_sha256": sha256_bytes(canonical_json_bytes(stable_identity)),
        "verified_files": verified_files,
        "scenarios": scenarios,
        "question_rows": question_rows,
        "qid_bytes": qid_bytes,
        "question_index_bytes": question_index_bytes,
        "image_references": image_references,
        "referenced_images": referenced_images,
        "unreferenced_images": unreferenced_images,
    }


def atomic_write(path: Path, payload: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--required-marker", type=Path, required=True)
    parser.add_argument("--forbidden-marker", type=Path, required=True)
    parser.add_argument("--expected-questions", type=int, required=True)
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    evidence_root = args.evidence_root.resolve()
    required_marker = args.required_marker.resolve()
    forbidden_marker = args.forbidden_marker.resolve()
    validate_exact_child(dataset_root, ALLOWED_DATASET_SCOPES, "dataset root")
    validate_exact_child(evidence_root, ALLOWED_RUN_SCOPES, "evidence root")
    validate_under_scope(required_marker, ALLOWED_RUN_SCOPES, "required marker")
    validate_under_scope(forbidden_marker, ALLOWED_RUN_SCOPES, "forbidden marker")
    if evidence_root.exists():
        raise SystemExit(f"refusing existing evidence root: {evidence_root}")
    if not required_marker.is_file() or forbidden_marker.exists():
        raise SystemExit(
            f"materialization marker gate failed: required={required_marker}, forbidden={forbidden_marker}"
        )
    if args.expected_questions <= 0:
        raise SystemExit("expected question count must be positive")

    evidence_root.mkdir(parents=False)
    started_at = now()
    manifest_path = args.manifest.resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        audit = audit_dataset(dataset_root, manifest, args.expected_questions)
        question_path = evidence_root / "question-index.jsonl"
        qid_path = evidence_root / "QID_ORDER.txt"
        references_path = evidence_root / "image-references.json"
        identity_path = evidence_root / "dataset-integrity.json"
        atomic_write(question_path, audit["question_index_bytes"])
        atomic_write(qid_path, audit["qid_bytes"])
        atomic_write(
            references_path,
            json.dumps(
                {
                    "references": audit["image_references"],
                    "referenced_images": audit["referenced_images"],
                    "unreferenced_images": audit["unreferenced_images"],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            + b"\n",
        )
        result = {
            "schema_version": "agentenhance.memgallery_dataset_integrity.v1",
            "status": "TERMINAL_ACCEPTED",
            "started_at": started_at,
            "finished_at": now(),
            "dataset_root": str(dataset_root),
            "source_manifest": str(manifest_path),
            "source_manifest_sha256": sha256_file(manifest_path),
            "required_materialization_marker": str(required_marker),
            "forbidden_materialization_marker_absent": not forbidden_marker.exists(),
            "stable_identity": audit["stable_identity"],
            "dataset_semantic_identity_sha256": audit["dataset_semantic_identity_sha256"],
            "scenarios": audit["scenarios"],
            "verified_file_count": len(audit["verified_files"]),
            "verified_file_bytes": sum(row["bytes"] for row in audit["verified_files"]),
            "numeric_result_rows_added": 0,
            "dataset_files_modified": 0,
        }
        atomic_write(identity_path, json.dumps(result, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        sums_path = evidence_root / "EVIDENCE_SHA256SUMS"
        signed = [identity_path, question_path, qid_path, references_path]
        atomic_write(
            sums_path,
            "".join(f"{sha256_file(path)}  {path}\n" for path in signed).encode("utf-8"),
        )
        (evidence_root / "TERMINAL_ACCEPTED").touch()
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "dataset_semantic_identity_sha256": result[
                        "dataset_semantic_identity_sha256"
                    ],
                    **result["stable_identity"],
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.memgallery_dataset_integrity_failure.v1",
            "status": "TERMINAL_REJECTED",
            "started_at": started_at,
            "finished_at": now(),
            "dataset_root": str(dataset_root),
            "source_manifest": str(manifest_path),
            "source_manifest_sha256": sha256_file(manifest_path) if manifest_path.is_file() else None,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "dataset_retained": dataset_root.exists(),
            "dataset_files_modified": 0,
            "cleanup_authorized": False,
            "numeric_result_rows_added": 0,
        }
        failure_path = evidence_root / "dataset-integrity-failure.json"
        atomic_write(failure_path, json.dumps(failure, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        atomic_write(
            evidence_root / "EVIDENCE_SHA256SUMS",
            f"{sha256_file(failure_path)}  {failure_path}\n".encode("utf-8"),
        )
        (evidence_root / "TERMINAL_REJECTED").touch()
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
