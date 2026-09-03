#!/usr/bin/env python3
"""Seed Python-side RNGs, then execute the pinned WorldMemArena CLI module."""

from __future__ import annotations

import argparse
import os
import random
import runpy
import sys


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--unit-seed", type=int, required=True)
    args, remainder = parser.parse_known_args()
    seed = args.unit_seed
    if str(os.environ.get("PYTHONHASHSEED", "")) != str(seed):
        raise SystemExit("PYTHONHASHSEED must equal --unit-seed before interpreter startup")
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass
    try:
        import torch

        torch.manual_seed(seed)
    except ImportError:
        pass
    sys.argv = ["eval_framework"] + remainder
    runpy.run_module("eval_framework.cli", run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
