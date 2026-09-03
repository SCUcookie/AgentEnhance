from __future__ import annotations

import importlib.util
import json
import tempfile
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_wma_wave4_hindsight_adapter.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("hindsight_lifecycle_test", CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass
class Row:
    memory_id: str
    text: str
    raw_backend_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Item:
    memory_id: str
    text: str
    score: float
    image_path: str | None = None
    rank: int = 0


class HindsightLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_checker()

    def test_fixed_fixture_cardinality_and_earliest_fact(self) -> None:
        schemas = types.ModuleType("eval_framework.datasets.schemas")

        class Attachment:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class NormalizedTurn:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        schemas.Attachment = Attachment
        schemas.NormalizedTurn = NormalizedTurn
        import sys

        sys.modules["eval_framework.datasets.schemas"] = schemas
        sessions = self.module.build_turns(Path("/fixed/image.png"))
        self.assertEqual(len(sessions), 3)
        self.assertEqual(sum(len(turns) for _sid, turns in sessions), 24)
        self.assertIn(self.module.EARLIEST_FACT, sessions[0][1][0].text)
        self.assertEqual(sessions[0][1][0].attachments[0].image_id, self.module.IMAGE_ID)

    def test_common_invariants_require_official_trace_and_persistence(self) -> None:
        snapshot = [
            Row(
                memory_id="m1",
                raw_backend_id="m1",
                text=f"private project code is {self.module.EARLIEST_FACT}",
                metadata={"wma_image_ids": f'["{self.module.IMAGE_ID}"]'},
            )
        ]
        record = types.SimpleNamespace(
            items=[Item("m1", snapshot[0].text, 0.9)],
            raw_trace={
                "official_scores": [{"final": 0.9}],
                "internal_retain_calls": 3,
                "reflect_called": False,
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            pg0 = Path(directory) / "pg0"
            pg0.mkdir()
            (pg0 / "state").write_bytes(b"persistent")
            invariants = self.module.lifecycle_invariants(
                capabilities={
                    "caption_mediated": True,
                    "native_multimodal": False,
                    "reflect_excluded": True,
                },
                snapshot_before=snapshot,
                snapshot_after=snapshot,
                delta=snapshot,
                retrieval_before=record,
                retrieval_after=record,
                image_id=self.module.IMAGE_ID,
                pg0_root=pg0,
            )
        self.assertTrue(all(invariants.values()))

    def test_execution_source_validation_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            payload = b"official"
            (source / "module.py").write_bytes(payload)
            record = root / "record.json"
            record.write_text(
                json.dumps(
                    {
                        "status": "TERMINAL_ACCEPTED",
                        "source_revision": "5e71494702bc050b6d58e783e6761f6c6cf3b74b",
                        "files": [
                            {
                                "path": "module.py",
                                "bytes": len(payload),
                                "sha256": self.module.sha256_file(source / "module.py"),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "cardinality"):
                self.module.validate_execution_source(source, record)


if __name__ == "__main__":
    unittest.main()
