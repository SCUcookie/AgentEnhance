#!/usr/bin/env python3
"""Admit Wave1 recovery2 results using pre-complete-seed identities."""

from __future__ import annotations

import argparse
from pathlib import Path

from frozen_source_successor import execute_successor


PARENT_SHA256 = "90aeda29acbfb26fa422d9472dbe56b99cd47c6ffe6f99f44ab73a9da3de3293"
RENDERED_SHA256 = "309cee5fb468d7c2cb6b8cd4bd676591d696af05046bf18e5cdbae60ebedc697"
REPLACEMENTS = (
    (
        "FROZEN_BEFORE_NUMERIC_RUN",
        "FROZEN_BEFORE_COMPLETE_SEED_RESULTS",
        1,
    ),
    (
        "agentenhance.wma_local_result_admission.v2",
        "agentenhance.wma_local_result_admission.v3",
        1,
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--parent-script", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    return execute_successor(
        args.parent_script.resolve(),
        PARENT_SHA256,
        REPLACEMENTS,
        RENDERED_SHA256,
        remaining,
    )


if __name__ == "__main__":
    raise SystemExit(main())
