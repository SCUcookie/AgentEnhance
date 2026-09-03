#!/usr/bin/env python3
"""Launch vLLM while relaxing only GME's stale transformers upper bound."""

from __future__ import annotations

import runpy


def build_guarded_require_version(original):
    def guarded(requirement: str, hint: str | None = None) -> None:
        try:
            original(requirement, hint)
        except ImportError:
            normalized = "".join(str(requirement).split()).lower()
            if normalized.startswith("transformers<4.52"):
                print(
                    "AGENTENHANCE_GME_TRANSFORMERS_UPPER_BOUND_GUARD="
                    + str(requirement),
                    flush=True,
                )
                return
            raise

    return guarded


def main() -> int:
    from transformers.utils import versions

    versions.require_version = build_guarded_require_version(versions.require_version)
    runpy.run_module("vllm.entrypoints.openai.api_server", run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
