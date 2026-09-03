from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from frozen_source_successor import render_successor  # noqa: E402


class PromoteWmaLocalResultsV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.wrapper = importlib.import_module("promote_wma_local_results_v3")
        self.parent = SCRIPTS / "promote_wma_local_results_v2.py"

    def render(self) -> str:
        return render_successor(
            self.parent,
            self.wrapper.PARENT_SHA256,
            self.wrapper.REPLACEMENTS,
            self.wrapper.RENDERED_SHA256,
        )

    def test_only_status_and_output_schema_change(self) -> None:
        parent = self.parent.read_text(encoding="utf-8")
        rendered = self.render()
        expected = parent.replace(
            "FROZEN_BEFORE_NUMERIC_RUN",
            "FROZEN_BEFORE_COMPLETE_SEED_RESULTS",
        ).replace(
            "agentenhance.wma_local_result_admission.v2",
            "agentenhance.wma_local_result_admission.v3",
        )
        self.assertEqual(rendered, expected)
        self.assertIn("EXPECTED_SEEDS = {0, 1, 2}", rendered)
        self.assertIn("EXPECTED_SAMPLES = 150", rendered)
        self.assertIn("EXPECTED_QA = 7906", rendered)
        self.assertIn("summary/raw metric mismatch", rendered)

    def test_parent_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / self.parent.name
            changed.write_bytes(self.parent.read_bytes() + b"\n")
            with self.assertRaises(SystemExit):
                render_successor(
                    changed,
                    self.wrapper.PARENT_SHA256,
                    self.wrapper.REPLACEMENTS,
                    self.wrapper.RENDERED_SHA256,
                )


if __name__ == "__main__":
    unittest.main()
