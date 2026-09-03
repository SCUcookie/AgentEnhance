from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "project_wma_method_summaries_v2.py"
SPEC = importlib.util.spec_from_file_location("project_wma_method_summaries_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProjectWmaMethodSummariesV2Test(unittest.TestCase):
    def test_complete_bundle_identity_and_allowed_methods(self) -> None:
        bundle, allowed = MODULE.validate_bundle(ROOT / "comparisons")
        self.assertEqual(bundle["method_corpus"]["rows"], 30)
        self.assertEqual(len(allowed), 25)
        for implementation_id in ("wma-memoryos", "wma-memgas", "wma-hindsight", "wma-structmem"):
            self.assertIn(implementation_id, allowed)

    def test_blocked_and_proposed_rows_are_never_admissible(self) -> None:
        _, allowed = MODULE.validate_bundle(ROOT / "comparisons")
        self.assertTrue(MODULE.BLOCKED.isdisjoint(allowed))
        self.assertNotIn(MODULE.PROPOSED, allowed)

    def test_bundle_constants_are_current(self) -> None:
        self.assertEqual(
            MODULE.sha256_file(ROOT / "comparisons" / MODULE.BUNDLE_NAME),
            MODULE.BUNDLE_SHA256,
        )
        self.assertEqual(
            MODULE.sha256_file(ROOT / "comparisons" / "wma-main-table-spec.v4.json"),
            MODULE.SPEC_SHA256,
        )

    def test_accepts_current_three_seed_summary_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = {
                "status": "TERMINAL_ACCEPTED",
                "main_comparison_eligible": True,
                "implementation_id": "wma-memoryos",
                "seed_count": 3,
                "n_samples": 150,
                "n_qa": 7906,
                "metrics": {},
            }
            slices = {
                "metrics": {f"slice.{index}.n_valid": {} for index in range(52)}
            }
            audit = {
                "status": "TERMINAL_ACCEPTED",
                "seed_count": 3,
                "seed_set": [0, 1, 2],
                "n_samples": 150,
                "n_qa": 7906,
            }
            for name, payload in (
                ("method-seed-summary.json", summary),
                ("slice-seed-summary.json", slices),
                ("audit.json", audit),
            ):
                (root / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
            (root / "SHA256SUMS").write_text(
                "".join(
                    f"{MODULE.sha256_file(root / name)}  {root / name}\n"
                    for name in (
                        "method-seed-summary.json",
                        "slice-seed-summary.json",
                        "audit.json",
                    )
                ),
                encoding="utf-8",
            )
            (root / "TERMINAL_ACCEPTED").touch()
            implementation_id, payload = MODULE.load_accepted_summary(
                root, {"wma-memoryos"}
            )
            self.assertEqual(implementation_id, "wma-memoryos")
            self.assertEqual(payload["summary"]["n_samples"], 150)


if __name__ == "__main__":
    unittest.main()
