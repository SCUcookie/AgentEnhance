"""Register the project-owned StructMem adapter without editing WorldMemArena."""

from __future__ import annotations

from eval_framework.memory_adapters import registry


def _structmem_factory(**kwargs):
    from structmem_wma_adapter import StructMemAdapter

    return StructMemAdapter(**kwargs)


registry.EXTERNAL_ADAPTER_KEYS = registry.EXTERNAL_ADAPTER_KEYS | frozenset({"StructMem"})
registry.EXTERNAL_ADAPTER_REGISTRY["StructMem"] = _structmem_factory
