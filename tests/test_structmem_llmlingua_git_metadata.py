from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_structmem_llmlingua_git_metadata.py"
SPEC = importlib.util.spec_from_file_location("structmem_model_metadata", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StructMemModelMetadataTest(unittest.TestCase):
    def test_frozen_identity_and_no_model_target(self) -> None:
        self.assertEqual(MODULE.REVISION, "5f0c82792b7ea14c6484e015b6a072009496b7f2")
        self.assertIn("model-metadata", MODULE.TARGET_RELATIVE.as_posix())
        self.assertLessEqual(MODULE.MAX_GIT_BYTES, 64 * 1024 * 1024)

    def test_lfs_pointer_parser(self) -> None:
        payload = (
            b"version https://git-lfs.github.com/spec/v1\n"
            b"oid sha256:" + b"a" * 64 + b"\nsize 709000000\n"
        )
        self.assertEqual(
            MODULE.parse_lfs_pointer(payload),
            {"sha256": "a" * 64, "bytes": 709000000},
        )
        self.assertIsNone(MODULE.parse_lfs_pointer(b"real model bytes"))

    def test_project_root_is_fail_closed(self) -> None:
        self.assertEqual(
            MODULE.validate_project_root(Path("/data1/example/AgentEnhance")),
            Path("/data1/example/AgentEnhance"),
        )
        with self.assertRaises(ValueError):
            MODULE.validate_project_root(Path("/tmp/AgentEnhance"))


if __name__ == "__main__":
    unittest.main()
