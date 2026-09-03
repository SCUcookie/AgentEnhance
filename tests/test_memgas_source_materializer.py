from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_memgas_source.py"
SPEC = importlib.util.spec_from_file_location("materialize_memgas_source", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MemgasSourceMaterializerTest(unittest.TestCase):
    def test_frozen_identity_and_project_scope(self) -> None:
        self.assertEqual(
            MODULE.REVISION,
            "c2d4e9fdc331074802a711baf4371197f9194399",
        )
        self.assertEqual(MODULE.SOURCE_RELATIVE.name, "memgas")
        self.assertEqual(MODULE.SOURCE_RELATIVE.parts[0], "third_party")
        self.assertEqual(
            MODULE.validate_project_root(Path("/data1/example/AgentEnhance")),
            Path("/data1/example/AgentEnhance"),
        )
        with self.assertRaises(ValueError):
            MODULE.validate_project_root(Path("/tmp/AgentEnhance"))
        with self.assertRaises(ValueError):
            MODULE.validate_project_root(Path("/data1/example/not-the-project"))

    def test_tracked_file_inventory_uses_git_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            (root / "untracked.txt").write_text("not authority\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
            self.assertEqual(MODULE.tracked_files(root), [Path("README.md")])

    def test_evidence_inventory_excludes_sentinals_and_itself(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source-materialization.json").write_text("{}\n", encoding="utf-8")
            (root / "TERMINAL_ACCEPTED").touch()
            MODULE.evidence_inventory(root)
            inventory = (root / "EVIDENCE_SHA256SUMS").read_text(encoding="utf-8")
            self.assertIn("source-materialization.json", inventory)
            self.assertNotIn("TERMINAL_ACCEPTED", inventory)
            self.assertNotIn("EVIDENCE_SHA256SUMS", inventory)


if __name__ == "__main__":
    unittest.main()
