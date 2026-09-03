from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "scripts" / "wma_wave3_overlay"


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


def install_eval_stubs() -> None:
    eval_framework = types.ModuleType("eval_framework")
    datasets = types.ModuleType("eval_framework.datasets")
    schemas = types.ModuleType("eval_framework.datasets.schemas")
    schemas.Attachment = Attachment
    schemas.NormalizedTurn = NormalizedTurn
    schemas.MemorySnapshotRecord = MemorySnapshotRecord
    schemas.MemoryDeltaRecord = MemoryDeltaRecord
    schemas.RetrievalItem = RetrievalItem
    schemas.RetrievalRecord = RetrievalRecord
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


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Wave3AdapterOverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_eval_stubs()
        cls.memoryos = load("memoryos_wma_adapter_test", OVERLAY / "memoryos_wma_adapter.py")
        cls.memgas = load("memgas_wma_adapter_test", OVERLAY / "memgas_wma_adapter.py")

    def test_caption_text_retains_image_identity(self) -> None:
        turn = NormalizedTurn(
            sample_id="sample",
            session_id="session",
            turn_index=0,
            role="user",
            text="remember this",
            attachments=(Attachment(caption="desk and lamp", image_id="image-7"),),
        )
        self.assertIn("image_id=image-7", self.memoryos._turn_text(turn))
        self.assertIn("desk and lamp", self.memgas._turn_text(turn))

    def test_memoryos_embedding_overlay_forwards_configured_path(self) -> None:
        calls = []

        class Updater:
            pass

        utilities = types.SimpleNamespace(
            get_embedding=lambda text, **kwargs: calls.append((text, kwargs)) or [1.0]
        )
        self.memoryos.MemoryOSAdapter._install_embedding_path_overlay(Updater, utilities)
        updater = Updater()
        updater.mid_term_memory = types.SimpleNamespace(
            embedding_model_name="/frozen/model",
            embedding_model_kwargs={"device": "cpu"},
        )
        self.assertEqual(updater._get_embedding_for_page("hello"), [1.0])
        self.assertEqual(
            calls,
            [("hello", {"model_name": "/frozen/model", "device": "cpu"})],
        )

    def test_memgas_gmm_overlay_records_and_reraises(self) -> None:
        class FailingGMM:
            def __init__(self, *args, **kwargs):
                pass

            def fit(self, *args, **kwargs):
                raise ValueError("fixture failure")

        adapter = self.memgas.MemGASAdapter.__new__(self.memgas.MemGASAdapter)
        adapter._fallback_events = []
        module = types.SimpleNamespace(GaussianMixture=FailingGMM)
        adapter._install_gmm_audit_overlay(module)
        with self.assertRaisesRegex(ValueError, "fixture failure"):
            module.GaussianMixture(n_components=2).fit([[0.0], [1.0]])
        self.assertEqual(adapter._fallback_events[0]["operation"], "fit")


if __name__ == "__main__":
    unittest.main()
