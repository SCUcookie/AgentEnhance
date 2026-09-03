from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "scripts" / "wma_wave4_overlay" / "hindsight_wma_adapter.py"


@dataclass(frozen=True)
class Attachment:
    caption: str
    type: str = "image_caption"
    image_id: str | None = None
    file_path: str | None = None


@dataclass(frozen=True)
class NormalizedTurn:
    sample_id: str
    session_id: str
    turn_index: int
    role: str
    text: str
    attachments: tuple[Attachment, ...] = ()
    timestamp: str | None = None


@dataclass(frozen=True)
class MemorySnapshotRecord:
    memory_id: str
    text: str
    session_id: str
    status: str
    source: str | None = None
    raw_backend_id: str | None = None
    raw_backend_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryDeltaRecord:
    session_id: str
    op: str
    text: str
    linked_previous: tuple[str, ...] = ()
    raw_backend_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalItem:
    rank: int
    memory_id: str
    text: str
    score: float
    raw_backend_id: str | None = None
    image_path: str | None = None


@dataclass(frozen=True)
class RetrievalRecord:
    query: str
    top_k: int
    items: list[RetrievalItem]
    raw_trace: dict[str, Any] = field(default_factory=dict)


class MemoryAdapter:
    pass


def load_adapter():
    eval_framework = types.ModuleType("eval_framework")
    datasets = types.ModuleType("eval_framework.datasets")
    schemas = types.ModuleType("eval_framework.datasets.schemas")
    for item in (
        Attachment,
        NormalizedTurn,
        MemorySnapshotRecord,
        MemoryDeltaRecord,
        RetrievalItem,
        RetrievalRecord,
    ):
        setattr(schemas, item.__name__, item)
    adapters = types.ModuleType("eval_framework.memory_adapters")
    base = types.ModuleType("eval_framework.memory_adapters.base")
    base.MemoryAdapter = MemoryAdapter
    sys.modules.update(
        {
            "eval_framework": eval_framework,
            "eval_framework.datasets": datasets,
            "eval_framework.datasets.schemas": schemas,
            "eval_framework.memory_adapters": adapters,
            "eval_framework.memory_adapters.base": base,
        }
    )
    spec = importlib.util.spec_from_file_location("hindsight_wma_adapter_test", ADAPTER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClient:
    def __init__(self) -> None:
        self.retain_calls = []

    def retain_batch(self, **kwargs):
        self.retain_calls.append(kwargs)
        return types.SimpleNamespace(
            success=True,
            var_async=False,
            items_count=len(kwargs["items"]),
        )


class HindsightAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_adapter()

    def bare_adapter(self):
        adapter = self.module.HindsightAdapter.__new__(self.module.HindsightAdapter)
        adapter._client = FakeClient()
        adapter._bank_id = "bank"
        adapter._sessions = {}
        adapter._previous_snapshot_ids = set()
        adapter._internal_retain_calls = 0
        return adapter

    def test_caption_mediated_turn_retains_image_identity(self) -> None:
        turn = NormalizedTurn(
            sample_id="sample",
            session_id="session",
            turn_index=0,
            role="user",
            text="remember this",
            attachments=(Attachment(caption="desk and lamp", image_id="image-7"),),
        )
        rendered = self.module._turn_text(turn)
        self.assertIn("image_id=image-7", rendered)
        self.assertIn("desk and lamp", rendered)

    def test_end_session_calls_one_synchronous_batch(self) -> None:
        adapter = self.bare_adapter()
        adapter._sessions["session"] = [
            NormalizedTurn("sample", "session", 0, "user", "code is blue", timestamp="2026-01-01T00:00:00Z"),
            NormalizedTurn("sample", "session", 1, "assistant", "noted"),
            NormalizedTurn("sample", "session", 2, "user", "object is red"),
            NormalizedTurn("sample", "session", 3, "assistant", "saved"),
        ]
        adapter.end_session("session")
        self.assertEqual(len(adapter._client.retain_calls), 1)
        call = adapter._client.retain_calls[0]
        self.assertFalse(call["retain_async"])
        self.assertEqual(call["document_id"], "session")
        self.assertEqual(len(call["items"]), 2)
        self.assertEqual(call["items"][0]["metadata"]["caption_mediated"], "true")

    def test_retrieve_uses_official_final_score_and_truncates_after_recall(self) -> None:
        adapter = self.bare_adapter()

        class Scores:
            def __init__(self, value):
                self.value = value

            def model_dump(self, exclude_none=True):
                return {"final": self.value, "semantic": self.value / 2}

        adapter._client.recall = lambda **kwargs: types.SimpleNamespace(
            results=[
                types.SimpleNamespace(id=f"m-{index}", text=f"fact-{index}", scores=Scores(0.9 - index / 10))
                for index in range(3)
            ],
            trace={"arms": ["semantic", "graph"]},
        )
        record = adapter.retrieve("query", top_k=2)
        self.assertEqual([item.memory_id for item in record.items], ["m-0", "m-1"])
        self.assertEqual(record.items[0].score, 0.9)
        self.assertEqual(record.raw_trace["backend_result_count"], 3)
        self.assertFalse(record.raw_trace["reflect_called"])

    def test_snapshot_exhausts_official_pagination(self) -> None:
        adapter = self.bare_adapter()
        pages = {
            0: types.SimpleNamespace(
                items=[{"id": "a", "text": "alpha", "type": "world", "metadata": {"wma_session_id": "s1"}}],
                total=2,
            ),
            1: types.SimpleNamespace(
                items=[{"id": "b", "text": "beta", "type": "observation", "document_id": "s2"}],
                total=2,
            ),
        }
        adapter._client.list_memories = lambda **kwargs: pages[kwargs["offset"]]
        rows = adapter.snapshot_memories()
        self.assertEqual([row.memory_id for row in rows], ["a", "b"])
        self.assertEqual([row.session_id for row in rows], ["s1", "s2"])
        self.assertTrue(all(row.metadata["caption_mediated"] for row in rows))

    def test_capabilities_exclude_native_multimodal_and_reflect(self) -> None:
        adapter = self.bare_adapter()
        capabilities = adapter.get_capabilities()
        self.assertTrue(capabilities["caption_mediated"])
        self.assertFalse(capabilities["native_multimodal"])
        self.assertTrue(capabilities["reflect_excluded"])


if __name__ == "__main__":
    unittest.main()
