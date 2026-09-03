#!/usr/bin/env python3
"""Apply Wave-2 runtime guards before executing the lifecycle checker."""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

from wma_wave2_runtime_guard import apply_runtime_guard


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--checker", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--image-path", type=Path, required=True)
    parser.add_argument("--image-sha256", required=True)
    args = parser.parse_args()
    if not args.checker.is_file():
        raise SystemExit("missing lifecycle checker")
    apply_runtime_guard(args.baseline)
    sys.argv = [
        str(args.checker),
        "--repo-root",
        str(args.repo_root),
        "--baseline",
        args.baseline,
        "--image-path",
        str(args.image_path),
        "--image-sha256",
        args.image_sha256,
    ]
    runpy.run_path(str(args.checker), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
