from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_structmem_uv_lock.py"
SPEC = importlib.util.spec_from_file_location("materialize_structmem_uv_lock", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StructMemUvLockMaterializerTest(unittest.TestCase):
    def test_command_disables_cache_progress_and_python_downloads(self) -> None:
        command = MODULE.lock_command(Path("/tools/uv"), Path("/python"))
        self.assertEqual(command[:2], ["/tools/uv", "lock"])
        for flag in ("--no-python-downloads", "--no-cache", "--no-progress"):
            self.assertIn(flag, command)

    def test_frozen_input_identity_and_cardinality(self) -> None:
        manifest = ROOT / "requirements" / "inputs" / "structmem-py311-lock-workspace.v1.toml"
        self.assertEqual(manifest.stat().st_size, MODULE.WORKSPACE_BYTES)
        self.assertEqual(MODULE.sha256_file(manifest), MODULE.WORKSPACE_SHA256)
        self.assertEqual(MODULE.EXPECTED_DIRECT_DEPENDENCIES, 58)

    def test_normalized_names_follow_pep503_shape(self) -> None:
        self.assertEqual(MODULE.normalized_name("pydantic_core"), "pydantic-core")
        self.assertEqual(MODULE.normalized_name("PyYAML"), "pyyaml")


if __name__ == "__main__":
    unittest.main()
