"""Register project-owned Wave-3 adapters without editing WorldMemArena source."""

from __future__ import annotations

from eval_framework.memory_adapters import registry


def _memoryos_factory(**kwargs):
    from memoryos_wma_adapter import MemoryOSAdapter

    return MemoryOSAdapter(**kwargs)


def _memgas_factory(**kwargs):
    from memgas_wma_adapter import MemGASAdapter

    return MemGASAdapter(**kwargs)


_FACTORIES = {
    "MemoryOS": _memoryos_factory,
    "MemGAS": _memgas_factory,
}
registry.EXTERNAL_ADAPTER_KEYS = registry.EXTERNAL_ADAPTER_KEYS | frozenset(_FACTORIES)
registry.EXTERNAL_ADAPTER_REGISTRY.update(_FACTORIES)
