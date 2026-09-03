#!/usr/bin/env python3
"""Archive the accepted recovery2 Wave1 table projection as a small overlay."""

from __future__ import annotations

import argparse
from pathlib import Path

from frozen_source_successor import execute_successor


PARENT_SHA256 = "483a7db27227e95263f1c742584d5d517f88616fcc482058c966df29e0f24331"
RENDERED_SHA256 = "d842eedadcd482c6ff8b12f9f9fddcafa51ebdb983681c956bc77b54c719dbc1"
REPLACEMENTS = (
    (
        "wma-r1-wave1-20260903-v1",
        "wma-r1-wave1-recovery2-20260904-v1",
        1,
    ),
    (
        "wma-r1-wave1-table-projection-20260904-v2",
        "wma-r1-wave1-table-projection-recovery2-20260904-v3",
        3,
    ),
    (
        "agentenhance.wma_wave1_archive.v1",
        "agentenhance.wma_wave1_archive.v2",
        1,
    ),
    (
        "agentenhance.wma_wave1_table_projection.v2",
        "agentenhance.wma_wave1_table_projection.v3",
        1,
    ),
    (
        "agentenhance.wma_wave1_projection_archive.v2",
        "agentenhance.wma_wave1_projection_archive.v3",
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
