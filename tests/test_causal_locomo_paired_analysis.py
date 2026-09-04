from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.causal_locomo_paired_analysis import (
    benjamini_hochberg_adjust,
    holm_adjust,
    paired_statistics,
    write_analysis,
)


class CausalLocomoPairedAnalysisTests(unittest.TestCase):
    def test_cluster_paired_effect_is_deterministic_and_direction_aware(self) -> None:
        first = paired_statistics(
            [1.0, 0.9, 0.8, 0.7], [0.2, 0.3, 0.4, 0.5],
            direction="higher", randomization_key="quality",
            bootstrap_replicates=500, permutation_replicates=1000,
        )
        second = paired_statistics(
            [1.0, 0.9, 0.8, 0.7], [0.2, 0.3, 0.4, 0.5],
            direction="higher", randomization_key="quality",
            bootstrap_replicates=500, permutation_replicates=1000,
        )
        self.assertEqual(first, second)
        self.assertEqual(first["wins_a"], 4)
        self.assertEqual(first["outcome"], "IMPROVEMENT")
        lower = paired_statistics(
            [0.1, 0.2, 0.1], [0.8, 0.7, 0.9],
            direction="lower", randomization_key="risk",
            bootstrap_replicates=500, permutation_replicates=1000,
        )
        self.assertEqual(lower["wins_a"], 3)
        self.assertEqual(lower["outcome"], "IMPROVEMENT")

    def test_holm_and_bh_adjustments_are_monotone_and_bounded(self) -> None:
        raw = {"a": 0.001, "b": 0.02, "c": 0.04, "d": 0.8}
        holm = holm_adjust(raw)
        bh = benjamini_hochberg_adjust(raw)
        self.assertTrue(all(raw[key] <= holm[key] <= 1.0 for key in raw))
        self.assertTrue(all(raw[key] <= bh[key] <= 1.0 for key in raw))
        ordered = sorted(raw, key=raw.get)
        self.assertEqual([holm[key] for key in ordered], sorted(holm.values()))
        self.assertEqual([bh[key] for key in ordered], sorted(bh.values()))

    def test_nonfinite_or_unpaired_inputs_fail_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "equally sized"):
            paired_statistics(
                [1.0], [], direction="higher", randomization_key="x",
                bootstrap_replicates=10, permutation_replicates=10,
            )
        with self.assertRaisesRegex(RuntimeError, "non-finite"):
            paired_statistics(
                [float("nan")], [0.0], direction="higher", randomization_key="x",
                bootstrap_replicates=10, permutation_replicates=10,
            )

    def test_writer_rejects_partial_analysis_before_creating_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "analysis"
            with self.assertRaisesRegex(RuntimeError, "cardinality"):
                write_analysis(
                    root, quality_rows=[], cost_rows=[], evaluation_inventory_sha256="a" * 64,
                )
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
