#!/usr/bin/env python3
"""Static checks for the Wave-1 archive partition."""

from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("wave1_archive", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = load_module(ROOT / "scripts/remote_archive_wma_wave1.py")
    all_members = []
    for implementation_id, slug in module.METHODS:
        members = module.members_for_method(implementation_id, slug)
        assert len(members) == 7
        assert members[-1] == f"{module.SUMMARY}/{implementation_id}"
        all_members.extend(members)
    assert len(all_members) == len(set(all_members)) == 28
    scheduler = [member for member in all_members if "-aggregate" not in member and not member.startswith(module.SUMMARY)]
    aggregates = [member for member in all_members if member.endswith("-aggregate")]
    summaries = [member for member in all_members if member.startswith(module.SUMMARY)]
    assert len(scheduler) == 12 and len(aggregates) == 12 and len(summaries) == 4
    assert str(module.ARCHIVE_ROOT).startswith("/data2/2026/ldh/AgentEnhance/archives/")
    manifest = json.loads(
        (ROOT / "comparisons/wma-r1-wave1-archive-prefreeze.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["status"] == "FROZEN_BEFORE_WAVE1_TERMINAL"
    assert manifest["destination_root"] == str(module.ARCHIVE_ROOT)
    assert manifest["partition"]["archive_count"] == 5
    assert manifest["transfer"]["default_rate_limit_kbit_per_second"] == 4096
    for path_key, sha_key in (
        ("archiver", "archiver_sha256"),
        ("downloader", "downloader_sha256"),
    ):
        path = ROOT / manifest["implementation"][path_key]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["implementation"][sha_key]
    print("wave1-archive-static-test=PASS archives=5 scheduler=12 aggregates=12 summaries=4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
