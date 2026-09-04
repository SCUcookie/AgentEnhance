#!/usr/bin/env python3
"""Validate exhaustive result-free coverage of recent registered methods."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "recent-method-execution-coverage-audit.v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    audit = json.loads(PATH.read_text(encoding="utf-8"))
    if audit.get("status") != "TERMINAL_ACCEPTED_RESULT_FREE_COVERAGE_AUDIT":
        raise SystemExit("recent-method coverage status drift")
    for parent in audit["bound_inputs"]:
        if sha256(ROOT / parent["path"]) != parent["sha256"]:
            raise SystemExit(f"recent-method coverage parent drift: {parent['path']}")
    with (ROOT / "comparisons" / "baseline-register.v3.csv").open(newline="", encoding="utf-8") as handle:
        registry = list(csv.DictReader(handle))
    recent = {
        row["method_id"]: row for row in registry
        if row["year"] in {"2025", "2026"} and row["method_id"] != "agentenhance-ceu"
    }
    if len(recent) != 29 or len(recent) != audit["scope"]["external_registry_rows"]:
        raise SystemExit("recent external registry cardinality drift")
    partition = audit["exhaustive_partition"]
    categories = [
        set(partition["same_protocol_numeric_route"]),
        set(partition["protocol_blocked_gold_or_label_leak"]),
        set(partition["source_or_license_blocked"]),
        set(partition["deprecated_alias_no_separate_numeric_entity"]),
        set(partition["different_task_separate_report"]),
        set(partition["different_benchmark_separate_report"]),
        set(partition["literature_only_no_local_claim"]),
    ]
    flattened = set().union(*categories)
    if flattened != set(recent) or sum(len(group) for group in categories) != len(flattened):
        raise SystemExit("recent methods are missing or duplicated across coverage partitions")
    if partition["same_protocol_numeric_route_count"] != 15 or partition["partition_rows_total"] != 29:
        raise SystemExit("recent-method coverage partition count drift")
    blockers = set(partition["source_or_license_blocked"])
    expected_blocker_status = {
        "memory-r1": "code-not-released",
        "apex-mem": "no-official-code-verified",
        "lightmem": "no-official-code-verified",
        "hela-mem": "license-audit-blocked",
    }
    if blockers != set(expected_blocker_status) or any(
        recent[method]["adapter_status"] != status for method, status in expected_blocker_status.items()
    ):
        raise SystemExit("source or license blocker status drift")
    if partition["deprecated_alias_no_separate_numeric_entity"] != {"omnimem-agent": "omni-simplemem"}:
        raise SystemExit("recent-method alias resolution drift")
    maturity = audit["numeric_route_maturity"]
    maturity_groups = [
        set(maturity["lifecycle_accepted_before_numeric_execution"]),
        set(maturity["result_free_dependency_or_adapter_preparation_exists"]),
        set(maturity["registered_source_or_native_protocol_route_not_yet_lifecycle_accepted"]),
    ]
    numeric_routes = set(partition["same_protocol_numeric_route"])
    if (
        set().union(*maturity_groups) != numeric_routes
        or sum(len(group) for group in maturity_groups) != len(numeric_routes)
        or maturity["maturity_partition_total"] != 15
        or maturity["accepted_local_numeric_methods"] != 0
    ):
        raise SystemExit("numeric-route maturity partition drift")
    with (ROOT / "comparisons" / "wma-execution-matrix.v3.csv").open(newline="", encoding="utf-8") as handle:
        wma_methods = {row["method_id"] for row in csv.DictReader(handle)}
    memgallery = json.loads((ROOT / "comparisons" / "memgallery-static-method-entry-prefreeze.v1.json").read_text())
    memgallery_methods = {row["method_id"] for row in memgallery["methods"]}
    if (
        len(numeric_routes & wma_methods) != 14
        or len(numeric_routes & memgallery_methods) != 7
        or (numeric_routes & (wma_methods | memgallery_methods)) != numeric_routes
    ):
        raise SystemExit("track-specific recent numeric route coverage drift")
    with (ROOT / "comparisons" / "reproduced-results.v1.csv").open(newline="", encoding="utf-8") as handle:
        reproduced = list(csv.DictReader(handle))
    if reproduced or audit["scope"]["local_main_result_rows_at_audit"] != 0:
        raise SystemExit("coverage audit is no longer result-free")
    policy = audit["result_policy"]
    if (
        not policy["same_protocol_local_values_required"]
        or any(policy[key] for key in (
            "official_values_fill_missing_cells", "development_values_fill_missing_cells",
            "blocked_rows_removed_from_internal_master", "different_tasks_or_benchmarks_pooled",
            "alias_duplicate_numeric_rows", "future_method_removal_based_on_score",
        ))
    ):
        raise SystemExit("recent-method local-results policy drift")
    print(json.dumps({
        "status": "PASS",
        "recent_external_rows": len(recent),
        "same_protocol_numeric_routes": len(numeric_routes),
        "source_or_license_blockers": len(blockers),
        "protocol_blockers": len(partition["protocol_blocked_gold_or_label_leak"]),
        "separate_or_literature_rows": sum(len(group) for group in categories[-3:]),
        "local_main_result_rows": len(reproduced),
        "audit_sha256": sha256(PATH),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
