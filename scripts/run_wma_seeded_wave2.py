#!/usr/bin/env python3
"""Seed RNGs, apply the frozen Wave-2 runtime guard, and run WMA."""

from __future__ import annotations

import argparse
import os
import random
import runpy
import sys

from wma_wave2_runtime_guard import apply_runtime_guard


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--unit-seed", type=int, required=True)
    parser.add_argument("--baseline", required=True)
    args, remainder = parser.parse_known_args()
    if str(os.environ.get("PYTHONHASHSEED", "")) != str(args.unit_seed):
        raise SystemExit("PYTHONHASHSEED must equal --unit-seed before interpreter startup")
    apply_runtime_guard(args.baseline)
    random.seed(args.unit_seed)
    try:
        import numpy as np

        np.random.seed(args.unit_seed)
    except ImportError:
        pass
    try:
        import torch

        torch.manual_seed(args.unit_seed)
    except ImportError:
        pass
    sys.argv = ["eval_framework", "--baseline", args.baseline, *remainder]
    runpy.run_module("eval_framework.cli", run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
