#!/usr/bin/env python3
"""Run the immutable Wave1 postprocessor against recovery2 roots only."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from frozen_source_successor import execute_successor


PARENT_SHA256 = "538c9b7f658a02534b4c432d43157ced9645707ad8f7022e444cf13586e5036b"
RENDERED_SHA256 = "e1abc88cfecdee725ca0e6bc9d17e8ae18836cac260312f8d1a8858f2b66446e"
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
        "wma-r1-full-{slug}-seed{seed}-20260903-v1",
        "wma-r1-full-{slug}-seed{seed}-recovery2-20260904-v1",
        3,
    ),
    (
        "agentenhance-wma-wave1-controller-r1",
        "agentenhance-wma-wave1-controller-r2-v1",
        1,
    ),
    (
        "full-{session_slug}-s{seed}-v1",
        "full-{session_slug}-s{seed}-r2-v1",
        1,
    ),
    (
        "wma-r1-three-seed-{slug.replace('_', '-')}-20260903-v1",
        "wma-r1-three-seed-{slug.replace('_', '-')}-recovery2-20260904-v1",
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
