from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_hindsight_source.py"


def load_module():
    spec = importlib.util.spec_from_file_location("materialize_hindsight_source_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HindsightSourceMaterializerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_frozen_identity_and_project_scope(self) -> None:
        self.assertEqual(
            self.module.REVISION,
            "5e71494702bc050b6d58e783e6761f6c6cf3b74b",
        )
        self.assertEqual(
            self.module.validate_project_root(Path("/data1/2026/ldh/AgentEnhance")),
            Path("/data1/2026/ldh/AgentEnhance"),
        )
        with self.assertRaisesRegex(ValueError, "under /data1 or /data2"):
            self.module.validate_project_root(Path("/tmp/AgentEnhance"))

    def test_weight_suffixes_and_lfs_are_fail_closed(self) -> None:
        self.assertIn(".safetensors", self.module.PROHIBITED_SUFFIXES)
        self.assertIn(".pt", self.module.PROHIBITED_SUFFIXES)
        self.assertTrue(
            self.module.LFS_POINTER_PREFIX.startswith(b"version https://git-lfs")
        )


if __name__ == "__main__":
    unittest.main()
