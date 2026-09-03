from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_wma_wave4_hindsight_execution_source.py"
SPEC = importlib.util.spec_from_file_location(
    "materialize_wma_wave4_hindsight_execution_source", SCRIPT
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Wave4HindsightExecutionSourceTest(unittest.TestCase):
    def test_expected_identity_and_cardinality_are_frozen(self) -> None:
        self.assertEqual(len(MODULE.EXPECTED_REVISION), 40)
        self.assertEqual(MODULE.EXPECTED_FILE_COUNT, 563)
        self.assertEqual(MODULE.EXPECTED_TOTAL_BYTES, 9_417_481)

    def test_selection_keeps_runtime_packages_and_rejects_tests(self) -> None:
        self.assertTrue(MODULE.selected(Path("hindsight-api-slim/hindsight_api/config.py")))
        self.assertTrue(MODULE.selected(Path("hindsight-all/pyproject.toml")))
        self.assertTrue(
            MODULE.selected(
                Path("hindsight-clients/python/hindsight_client_api/models/recall_result.py")
            )
        )
        self.assertFalse(MODULE.selected(Path("hindsight-api-slim/tests/test_api.py")))
        self.assertFalse(MODULE.selected(Path("hindsight-docs/docs/index.md")))

    def test_copy_uses_only_tracked_selected_regular_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            destination = Path(directory) / "destination"
            (source / "hindsight-all" / "hindsight").mkdir(parents=True)
            (source / "hindsight-all" / "tests").mkdir(parents=True)
            (source / "hindsight-all" / "hindsight" / "server.py").write_text(
                "VALUE = 1\n", encoding="utf-8"
            )
            (source / "hindsight-all" / "tests" / "test_server.py").write_text(
                "not runtime\n", encoding="utf-8"
            )
            (source / "untracked.py").write_text("not authority\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=source, check=True)
            subprocess.run(
                [
                    "git",
                    "add",
                    "hindsight-all/hindsight/server.py",
                    "hindsight-all/tests/test_server.py",
                ],
                cwd=source,
                check=True,
            )
            rows = MODULE.copy_source(source, destination)
            self.assertEqual(
                [row["path"] for row in rows],
                ["hindsight-all/hindsight/server.py"],
            )
            self.assertFalse((destination / "hindsight-all" / "tests").exists())
            self.assertFalse((destination / "untracked.py").exists())


if __name__ == "__main__":
    unittest.main()
