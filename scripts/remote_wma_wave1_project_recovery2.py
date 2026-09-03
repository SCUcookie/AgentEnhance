#!/usr/bin/env python3
"""Run the immutable complete Wave1 projection against recovery2 summaries."""

from __future__ import annotations

import argparse
from pathlib import Path

from frozen_source_successor import execute_successor


PARENT_SHA256 = "241b43ec80615c1a7579c61a2f28eaf4144f2311f17d72eee1a373b14ddd68f2"
RENDERED_SHA256 = "1197cef004d4e67494b926bbc1be5f75b843c38a4a2abd80750ee3a7fce73d8d"
REPLACEMENTS = (
    (
        "wma-r1-wave1-three-seed-summaries-20260903-v1",
        "wma-r1-wave1-three-seed-summaries-recovery2-20260904-v1",
        1,
    ),
    (
        "wma-r1-wave1-table-projection-20260904-v2",
        "wma-r1-wave1-table-projection-recovery2-20260904-v3",
        1,
    ),
    (
        "agentenhance.wma_wave1_table_projection.v2",
        "agentenhance.wma_wave1_table_projection.v3",
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
