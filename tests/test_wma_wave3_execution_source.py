from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_wma_wave3_execution_source.py"
SPEC = importlib.util.spec_from_file_location("materialize_wma_wave3_execution_source", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Wave3ExecutionSourceTest(unittest.TestCase):
    def test_expected_source_revisions_are_immutable(self) -> None:
        self.assertEqual(len(MODULE.EXPECTED_REVISIONS), 2)
        self.assertTrue(all(len(value) == 40 for value in MODULE.EXPECTED_REVISIONS.values()))

    def test_memgas_copy_uses_tracked_source_and_excludes_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=source, check=True)
            (source / "quickstart" / "__pycache__").mkdir(parents=True)
            (source / "quickstart" / "memory.py").write_text("VALUE = 1\n", encoding="utf-8")
            (source / "quickstart" / "__pycache__" / "memory.pyc").write_bytes(b"bytecode")
            (source / "untracked.txt").write_text("not authority\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "quickstart/memory.py", "quickstart/__pycache__/memory.pyc"],
                cwd=source,
                check=True,
            )
            rows = MODULE.copy_source(source, destination, "memgas")
            self.assertEqual([row["path"] for row in rows], ["quickstart/memory.py"])
            self.assertTrue(
                (destination / "memgas_source" / "quickstart" / "memory.py").is_file()
            )
            self.assertFalse(
                (destination / "memgas_source" / "quickstart" / "__pycache__").exists()
            )
            self.assertFalse((destination / "memgas_source" / "untracked.txt").exists())


if __name__ == "__main__":
    unittest.main()
