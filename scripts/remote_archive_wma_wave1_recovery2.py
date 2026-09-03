#!/usr/bin/env python3
"""Run the immutable five-part Wave1 archiver against recovery2 evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from frozen_source_successor import execute_successor


PARENT_SHA256 = "03e0ac1348c7dbc3b7e9cfda8afd1432311b158c1a564f6dec117e3e7a284a93"
RENDERED_SHA256 = "20e0da782ea7b751626328bc9985570c0f5d235f1adc063dacacdbe3c2e4df18"
REPLACEMENTS = (
    (
        "wma-r1-wave1-controller-recovery1-20260903-v1",
        "wma-r1-wave1-controller-recovery2-20260904-v1",
        1,
    ),
    (
        "wma-r1-wave1-three-seed-summaries-20260903-v1",
        "wma-r1-wave1-three-seed-summaries-recovery2-20260904-v1",
        1,
    ),
    (
        "wma-r1-wave1-20260903-v1",
        "wma-r1-wave1-recovery2-20260904-v1",
        1,
    ),
    (
        "wma-r1-full-{slug}-seed{seed}-20260903-v1",
        "wma-r1-full-{slug}-seed{seed}-recovery2-20260904-v1",
        3,
    ),
    (
        "agentenhance.wma_wave1_archive.v1",
        "agentenhance.wma_wave1_archive.v2",
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
