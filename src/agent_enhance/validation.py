from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List


ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
SHA256_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")


@dataclass(frozen=True)
class Issue:
    path: str
    message: str


def _load_json(path: Path, issues: List[Issue]) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        issues.append(Issue(str(path), f"invalid JSON: {error}"))
        return None


def _require_mapping(value: Any, path: Path, issues: List[Issue]) -> dict:
    if not isinstance(value, dict):
        issues.append(Issue(str(path), "top-level JSON value must be an object"))
        return {}
    return value


def _missing(record: dict, keys: Iterable[str]) -> List[str]:
    return [key for key in keys if key not in record]


def validate_project(root: Path) -> List[Issue]:
    root = root.resolve()
    issues: List[Issue] = []
    required_files = [
        "README.md",
        "AGENTS.md",
        "project.json",
        "docs/ARCHITECTURE.md",
        "docs/SOP.md",
        "docs/EVALUATION_PROTOCOL.md",
        "docs/SERVER_OPERATIONS.md",
        "schemas/dataset-manifest.v1.schema.json",
        "schemas/episode.v1.schema.json",
        "schemas/experiment-spec.v1.schema.json",
        "schemas/run-record.v1.schema.json",
        "schemas/run-event.v1.schema.json",
        "schemas/evaluation-report.v1.schema.json",
        "scripts/sftp_upload_limited.sh",
    ]
    for relative in required_files:
        if not (root / relative).is_file():
            issues.append(Issue(relative, "required file is missing"))

    project_path = root / "project.json"
    if project_path.is_file():
        project = _require_mapping(_load_json(project_path, issues), project_path, issues)
        if project.get("schema_version") != "agent_enhance_project.v1":
            issues.append(Issue("project.json", "unexpected schema_version"))
        if project.get("project_id") != "agent-enhance":
            issues.append(Issue("project.json", "project_id must be agent-enhance"))
        if project.get("origin") != "git@github.com:SCUcookie/AgentEnhance.git":
            issues.append(Issue("project.json", "origin does not match the declared GitHub repository"))
        server = project.get("server_policy", {})
        if server.get("storage_candidates") != ["/data1", "/data2"]:
            issues.append(Issue("project.json", "storage candidates must be /data1 and /data2"))

    for path in sorted((root / "schemas").glob("*.json")):
        schema = _require_mapping(_load_json(path, issues), path, issues)
        if schema and "$schema" not in schema:
            issues.append(Issue(str(path.relative_to(root)), "JSON Schema declaration is missing"))

    for path in sorted((root / "configs" / "experiments").glob("*.json")):
        record = _require_mapping(_load_json(path, issues), path, issues)
        if record:
            issues.extend(_validate_experiment(record, path.relative_to(root)))

    template = root / "datasets" / "templates" / "dataset-manifest.v1.json"
    if template.is_file():
        record = _require_mapping(_load_json(template, issues), template, issues)
        if record:
            issues.extend(_validate_dataset(record, template.relative_to(root), allow_pending=True))

    for registry_path, expected in [
        (root / "datasets" / "registry.json", "dataset_registry.v1"),
        (root / "experiments" / "registry.json", "experiment_registry.v1"),
    ]:
        if registry_path.is_file():
            registry = _require_mapping(_load_json(registry_path, issues), registry_path, issues)
            if registry.get("schema_version") != expected:
                issues.append(Issue(str(registry_path.relative_to(root)), "unexpected registry schema_version"))

    script = root / "scripts" / "sftp_upload_limited.sh"
    if script.is_file():
        body = script.read_text(encoding="utf-8")
        for required in ["sftp", "-l", "reput", "sha256sum", "/data[12]/", ".partial"]:
            if required not in body:
                issues.append(Issue(str(script.relative_to(root)), f"missing transfer safety primitive: {required}"))

    return issues


def _validate_dataset(record: dict, path: Path, allow_pending: bool) -> List[Issue]:
    issues: List[Issue] = []
    required = ["schema_version", "dataset_id", "version", "classification", "modalities", "authority", "splits", "digest"]
    missing = _missing(record, required)
    if missing:
        issues.append(Issue(str(path), f"missing fields: {', '.join(missing)}"))
        return issues
    if record["schema_version"] != "dataset_manifest.v1":
        issues.append(Issue(str(path), "unexpected dataset schema_version"))
    if not ID_PATTERN.fullmatch(str(record["dataset_id"])):
        issues.append(Issue(str(path), "invalid dataset_id"))
    if record["classification"] not in {"synthetic_public", "public_external", "private_local"}:
        issues.append(Issue(str(path), "invalid classification"))
    if not isinstance(record["modalities"], list) or not record["modalities"]:
        issues.append(Issue(str(path), "modalities must be a non-empty list"))
    authority = record.get("authority", {})
    if authority.get("immutable") is not True or authority.get("content_addressed") is not True:
        issues.append(Issue(str(path), "authority must be immutable and content-addressed"))
    if set(record.get("splits", {})) != {"train", "dev", "selection", "final"}:
        issues.append(Issue(str(path), "splits must contain train/dev/selection/final exactly"))
    digest = str(record.get("digest", ""))
    if digest == "pending" and allow_pending:
        pass
    elif not SHA256_PATTERN.fullmatch(digest):
        issues.append(Issue(str(path), "dataset digest must be a SHA-256"))
    return issues


def _validate_experiment(record: dict, path: Path) -> List[Issue]:
    issues: List[Issue] = []
    required = [
        "schema_version",
        "experiment_id",
        "status",
        "hypothesis",
        "changed_factor",
        "dataset",
        "arms",
        "seeds",
        "metrics",
        "decision_rule",
        "resources",
        "retry_policy",
    ]
    missing = _missing(record, required)
    if missing:
        issues.append(Issue(str(path), f"missing fields: {', '.join(missing)}"))
        return issues
    if record["schema_version"] != "experiment_spec.v1":
        issues.append(Issue(str(path), "unexpected experiment schema_version"))
    if not ID_PATTERN.fullmatch(str(record["experiment_id"])):
        issues.append(Issue(str(path), "invalid experiment_id"))
    if record["status"] not in {"draft", "frozen", "terminal"}:
        issues.append(Issue(str(path), "invalid experiment status"))

    arms = record.get("arms")
    if not isinstance(arms, list) or len(arms) < 2:
        issues.append(Issue(str(path), "at least two arms are required"))
    else:
        ids = [arm.get("arm_id") for arm in arms if isinstance(arm, dict)]
        if len(ids) != len(set(ids)):
            issues.append(Issue(str(path), "arm_id values must be unique"))
        if sum(1 for arm in arms if isinstance(arm, dict) and arm.get("role") == "baseline") != 1:
            issues.append(Issue(str(path), "exactly one baseline arm is required"))

    seeds = record.get("seeds")
    if not isinstance(seeds, list) or not seeds or len(seeds) != len(set(seeds)):
        issues.append(Issue(str(path), "seeds must be a non-empty unique list"))

    retry = record.get("retry_policy", {})
    if retry.get("automatic_retry") is not False:
        issues.append(Issue(str(path), "automatic retries are forbidden"))
    if retry.get("fresh_output_required") is not True:
        issues.append(Issue(str(path), "fresh output is required"))
    if not isinstance(retry.get("max_attempts"), int) or retry.get("max_attempts", 0) < 1:
        issues.append(Issue(str(path), "max_attempts must be at least one"))

    if record["status"] != "draft":
        dataset_digest = str(record.get("dataset", {}).get("digest", ""))
        if not SHA256_PATTERN.fullmatch(dataset_digest):
            issues.append(Issue(str(path), "frozen/terminal experiment requires a dataset SHA-256"))
    return issues
