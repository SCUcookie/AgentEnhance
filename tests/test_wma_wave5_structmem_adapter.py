from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "scripts" / "wma_wave5_overlay" / "structmem_wma_adapter.py"


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
    spec = importlib.util.spec_from_file_location("structmem_wma_adapter_test", ADAPTER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRetriever:
    def __init__(self, rows=None, hits=None):
        self.rows = list(rows or [])
        self.hits = list(hits or [])
        self.search_calls = []

    def scroll(self, **kwargs):
        return self.rows, None

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return self.hits[: kwargs["limit"]]


class FakeEmbedder:
    def __init__(self):
        self.queries = []

    def embed(self, query):
        self.queries.append(query)
        return [0.1, 0.2]


class FakeBackend:
    def __init__(self, details=None, summaries=None, detail_hits=None, summary_hits=None):
        self.embedding_retriever = FakeRetriever(details, detail_hits)
        self.summary_retriever = FakeRetriever(summaries, summary_hits)
        self.text_embedder = FakeEmbedder()
        self.add_calls = []
        self.summary_calls = []

    def add_memory(self, **kwargs):
        self.add_calls.append(kwargs)

    def summarize(self, **kwargs):
        self.summary_calls.append(kwargs)
        return {"total_summaries": 1}


class StructMemAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_adapter()

    def bare_adapter(self, storage: Path, backend: FakeBackend | None = None):
        adapter = self.module.StructMemAdapter.__new__(self.module.StructMemAdapter)
        adapter._backend = backend or FakeBackend()
        adapter._sessions = {}
        adapter._prompts = {"factual": "fact", "relational": "relation"}
        adapter._last_assigned_timestamp = None
        adapter._summary_calls = 0
        adapter._backend_session_ids = {}
        adapter._previous_snapshot_ids = set()
        adapter._active_storage = storage
        adapter._generation = 0
        adapter._lightmem_module = types.SimpleNamespace(
            GLOBAL_TOPIC_IDX=99,
            GLOBAL_LAST_SUMMARY_TIME=123,
        )
        return adapter

    def test_each_original_role_becomes_a_separate_user_source_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backend = FakeBackend(
                details=[types.SimpleNamespace(id="d1", payload={"memory": "fact"})],
                summaries=[types.SimpleNamespace(id="s1", payload={"summary": "summary"})],
            )
            adapter = self.bare_adapter(Path(directory), backend)
            adapter._sessions["session"] = [
                NormalizedTurn(
                    "sample",
                    "session",
                    0,
                    "user",
                    "remember blue",
                    (Attachment("a blue panel", image_id="image-7"),),
                    "2026-01-01T00:00:00Z",
                ),
                NormalizedTurn(
                    "sample",
                    "session",
                    1,
                    "assistant",
                    "I stored red",
                    timestamp="2026-01-01T00:00:00Z",
                ),
            ]
            adapter.end_session("session")
            self.assertEqual(len(backend.add_calls), 2)
            first, second = backend.add_calls
            self.assertEqual(first["messages"][0]["role"], "user")
            self.assertEqual(second["messages"][0]["role"], "user")
            self.assertEqual(first["messages"][1]["content"], "")
            self.assertEqual(second["messages"][1]["content"], "")
            self.assertIn("original_role=assistant", second["messages"][0]["content"])
            self.assertIn("image_id=image-7", first["messages"][0]["content"])
            self.assertFalse(first["force_segment"])
            self.assertTrue(second["force_segment"])
            self.assertFalse(first["force_extract"])
            self.assertTrue(second["force_extract"])
            self.assertLess(
                first["messages"][0]["time_stamp"],
                second["messages"][0]["time_stamp"],
            )

    def test_end_session_summarizes_before_return_with_frozen_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backend = FakeBackend()
            adapter = self.bare_adapter(Path(directory), backend)
            adapter._sessions["s"] = [NormalizedTurn("x", "s", 0, "user", "hello")]
            adapter.end_session("s")
            self.assertEqual(
                backend.summary_calls,
                [{
                    "retrieval_scope": "global",
                    "time_window": 3600,
                    "top_k_seeds": 15,
                    "process_all": True,
                }],
            )
            self.assertEqual(adapter._summary_calls, 1)

    def test_timestamp_guard_handles_missing_equal_and_out_of_order_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.bare_adapter(Path(directory))
            values = [
                adapter._assign_timestamp(None),
                adapter._assign_timestamp("1999-01-01T00:00:00Z"),
                adapter._assign_timestamp("1999-01-01T00:00:00Z"),
            ]
            self.assertEqual(values, sorted(values))
            self.assertEqual(len(set(values)), 3)

    def test_retrieval_shares_top_k_between_details_and_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backend = FakeBackend(
                detail_hits=[
                    {"id": "d1", "score": 0.9, "payload": {"memory": "detail one"}},
                    {"id": "d2", "score": 0.7, "payload": {"memory": "detail two"}},
                    {"id": "d3", "score": 0.3, "payload": {"memory": "detail three"}},
                ],
                summary_hits=[
                    {"id": "s1", "score": 0.8, "payload": {"summary": "summary one"}},
                    {"id": "s2", "score": 0.6, "payload": {"summary": "summary two"}},
                ],
            )
            adapter = self.bare_adapter(Path(directory), backend)
            record = adapter.retrieve("query", top_k=3)
            self.assertEqual([item.memory_id for item in record.items], ["detail:d1", "summary:s1", "detail:d2"])
            self.assertEqual(len(record.items), 3)
            self.assertEqual(backend.summary_retriever.search_calls[0]["limit"], 3)
            self.assertTrue(record.raw_trace["retrieval_budget_shared"])

    def test_reset_clears_upstream_module_globals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.bare_adapter(Path(directory))
            adapter._storage_root = Path(directory)
            adapter._generation = -1
            adapter._backend = None
            fake_backend = FakeBackend()
            adapter._new_backend = lambda storage: fake_backend
            adapter.reset()
            self.assertEqual(adapter._lightmem_module.GLOBAL_TOPIC_IDX, 0)
            self.assertIsNone(adapter._lightmem_module.GLOBAL_LAST_SUMMARY_TIME)
            self.assertTrue((Path(directory) / "generation-000").is_dir())


if __name__ == "__main__":
    unittest.main()
