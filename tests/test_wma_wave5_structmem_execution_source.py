from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_wma_wave5_structmem_execution_source.py"
SPEC = importlib.util.spec_from_file_location("structmem_execution_source", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StructMemExecutionSourceTest(unittest.TestCase):
    def test_expected_identity_and_cardinality_are_frozen(self) -> None:
        self.assertEqual(MODULE.EXPECTED_REVISION, "aa1c484cc6fd964c8ea1af897e36a0c3ba06d7db")
        self.assertEqual(MODULE.EXPECTED_FILE_COUNT, 66)
        self.assertEqual(MODULE.EXPECTED_TOTAL_BYTES, 344_766)

    def test_selection_keeps_runtime_and_rejects_other_methods(self) -> None:
        self.assertTrue(MODULE.selected(Path("src/lightmem/memory/lightmem.py")))
        self.assertTrue(MODULE.selected(Path("experiments/locomo/prompts.py")))
        self.assertTrue(MODULE.selected(Path("LICENSE")))
        self.assertFalse(MODULE.selected(Path("src/em2mem/memory/EM2Memory.py")))
        self.assertFalse(MODULE.selected(Path("src/fluxmem/agent.py")))
        self.assertFalse(MODULE.selected(Path("experiments/locomo/search_locomo.py")))
        self.assertFalse(MODULE.selected(Path("tests/test_sensory_memory.py")))

    def test_copy_uses_only_tracked_selected_regular_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            destination = Path(directory) / "destination"
            source.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=source, check=True)
            selected = source / "src/lightmem/memory/lightmem.py"
            selected.parent.mkdir(parents=True)
            selected.write_text("fixture\n", encoding="utf-8")
            excluded = source / "tests/test_fixture.py"
            excluded.parent.mkdir()
            excluded.write_text("excluded\n", encoding="utf-8")
            untracked = source / "src/lightmem/memory/untracked.py"
            untracked.write_text("untracked\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "src/lightmem/memory/lightmem.py", "tests/test_fixture.py"],
                cwd=source,
                check=True,
            )
            rows = MODULE.copy_source(source, destination)
            self.assertEqual([row["path"] for row in rows], ["src/lightmem/memory/lightmem.py"])
            self.assertFalse((destination / "tests/test_fixture.py").exists())
            self.assertFalse((destination / "src/lightmem/memory/untracked.py").exists())


if __name__ == "__main__":
    unittest.main()
