"""Register the project-owned Hindsight adapter without editing WorldMemArena."""

from __future__ import annotations

from eval_framework.memory_adapters import registry


def _hindsight_factory(**kwargs):
    from hindsight_wma_adapter import HindsightAdapter

    return HindsightAdapter(**kwargs)


registry.EXTERNAL_ADAPTER_KEYS = registry.EXTERNAL_ADAPTER_KEYS | frozenset({"Hindsight"})
registry.EXTERNAL_ADAPTER_REGISTRY["Hindsight"] = _hindsight_factory
