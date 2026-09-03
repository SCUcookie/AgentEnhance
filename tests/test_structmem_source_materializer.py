from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_structmem_source.py"
SPEC = importlib.util.spec_from_file_location("materialize_structmem_source", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StructMemSourceMaterializerTest(unittest.TestCase):
    def test_frozen_identity_and_project_scope(self) -> None:
        self.assertEqual(MODULE.REPOSITORY, "https://github.com/zjunlp/LightMem.git")
        self.assertEqual(MODULE.REVISION, "aa1c484cc6fd964c8ea1af897e36a0c3ba06d7db")
        self.assertEqual(MODULE.SOURCE_RELATIVE.name, "structmem-lightmem")
        self.assertEqual(MODULE.SOURCE_RELATIVE.parts[0], "third_party")
        self.assertEqual(
            MODULE.validate_project_root(Path("/data1/example/AgentEnhance")),
            Path("/data1/example/AgentEnhance"),
        )
        with self.assertRaises(ValueError):
            MODULE.validate_project_root(Path("/tmp/AgentEnhance"))

    def test_tracked_file_inventory_uses_git_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "LICENSE").write_text("MIT License fixture\n", encoding="utf-8")
            (root / "untracked.txt").write_text("not authority\n", encoding="utf-8")
            subprocess.run(["git", "add", "LICENSE"], cwd=root, check=True)
            self.assertEqual(MODULE.tracked_files(root), [Path("LICENSE")])

    def test_evidence_inventory_excludes_sentinels_and_itself(self) -> None:
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
