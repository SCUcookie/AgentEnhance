from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/promote_wma_local_results_v2.py"
SPEC = importlib.util.spec_from_file_location("promote_wma_local_results_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_inventory(root: Path, files: list[Path]) -> str:
    inventory = root / "SHA256SUMS"
    inventory.write_text(
        "".join(f"{sha256_file(path)}  {path}\n" for path in files), encoding="utf-8"
    )
    return sha256_file(inventory)


class PromoteLocalResultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog = MODULE.load_metric_catalog(
            ROOT / "comparisons/wma-method-seed-statistics-template.v1.csv"
        )
        self.matrix = MODULE.load_method_matrix(ROOT / "comparisons/wma-execution-matrix.v3.csv")
        self.identity_path = self.root / "identity.json"
        self.identity = {
            "schema_version": "agentenhance.wma_result_identity.v1",
            "status": "FROZEN_BEFORE_NUMERIC_RUN",
            "implementation_id": "wma-mmfu-single",
            "run_id": "synthetic-three-seed",
            "benchmark_id": "worldmemarena-2026",
            "track_id": "wma-lifecycle-matched-v1",
            "split": "small",
            "dataset_digest": "d" * 64,
            "code_commit": "c" * 40,
            "adapter_code_identity": "synthetic-adapter@v1",
            "backbone_id": "synthetic-backbone@v1",
            "retriever_id": "synthetic-retriever@v1",
            "evaluator_id": "synthetic-evaluator@v1",
        }
        self.identity_path.write_text(json.dumps(self.identity), encoding="utf-8")
        self.seed_roots: list[Path] = []
        source_evidence = []
        combined = {metric: {"seed_values": {}} for metric in self.catalog}
        for seed in range(3):
            seed_root = self.root / f"seed-{seed}"
            seed_root.mkdir()
            metrics = {}
            for index, metric in enumerate(sorted(self.catalog), start=1):
                value = float(index + seed)
                cursor = metrics
                parts = metric.split(".")
                for part in parts[:-1]:
                    cursor = cursor.setdefault(part, {})
                cursor[parts[-1]] = value
                combined[metric]["seed_values"][str(seed)] = value
            aggregate = seed_root / "aggregate_metrics.json"
            aggregate.write_text(json.dumps(metrics), encoding="utf-8")
            audit = seed_root / "audit.json"
            audit.write_text(
                json.dumps(
                    {
                        "status": "TERMINAL_ACCEPTED",
                        "main_comparison_eligible": True,
                        "baseline": "MMFU_Single",
                        "seed": seed,
                        "n_expected": 150,
                        "n_observed": 150,
                        "n_failed": 0,
                        "n_qa": 7906,
                        "source_commit": "c" * 40,
                        "dataset_manifest_sha256": "d" * 64,
                    }
                ),
                encoding="utf-8",
            )
            inventory_sha = write_inventory(seed_root, [aggregate, audit])
            (seed_root / "TERMINAL_ACCEPTED").touch()
            source_evidence.append(
                {
                    "seed": seed,
                    "aggregate_root": str(seed_root),
                    "artifact_inventory_sha256": inventory_sha,
                }
            )
            self.seed_roots.append(seed_root)
        summary_root = self.root / "summary"
        summary_root.mkdir()
        summary = summary_root / "method-seed-summary.json"
        summary.write_text(
            json.dumps(
                {
                    "status": "TERMINAL_ACCEPTED",
                    "main_comparison_eligible": True,
                    "implementation_id": "wma-mmfu-single",
                    "run_id": "synthetic-three-seed",
                    "baseline": "MMFU_Single",
                    "seed_count": 3,
                    "seeds": [0, 1, 2],
                    "n_samples": 150,
                    "n_qa": 7906,
                    "metrics": combined,
                    "source_evidence": source_evidence,
                }
            ),
            encoding="utf-8",
        )
        audit = summary_root / "audit.json"
        audit.write_text(
            json.dumps({"status": "TERMINAL_ACCEPTED", "seed_set": [0, 1, 2]}),
            encoding="utf-8",
        )
        write_inventory(summary_root, [summary, audit])
        (summary_root / "TERMINAL_ACCEPTED").touch()
        self.summary_root = summary_root

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_promotes_exactly_three_seeds_by_fifty_five_metrics(self) -> None:
        rows, source = MODULE.load_one_summary(
            self.summary_root, self.identity_path, self.matrix, self.catalog
        )
        self.assertEqual(len(rows), 165)
        self.assertEqual({int(row["seed"]) for row in rows}, {0, 1, 2})
        self.assertEqual(len({row["metric"] for row in rows}), 55)
        self.assertEqual({row["status"] for row in rows}, {"ACCEPTED_LOCAL_3SEED"})
        self.assertEqual({row["implementation_id"] for row in rows}, {"wma-mmfu-single"})
        self.assertEqual({row["method_id"] for row in rows}, {"mmfu-single"})
        self.assertEqual(source["implementation_id"], "wma-mmfu-single")

    def test_rejects_identity_mismatch(self) -> None:
        self.identity["dataset_digest"] = "e" * 64
        self.identity_path.write_text(json.dumps(self.identity), encoding="utf-8")
        with self.assertRaises(SystemExit):
            MODULE.load_one_summary(
                self.summary_root, self.identity_path, self.matrix, self.catalog
            )

    def test_rejects_raw_summary_value_mismatch(self) -> None:
        summary_path = self.summary_root / "method-seed-summary.json"
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        first_metric = sorted(self.catalog)[0]
        payload["metrics"][first_metric]["seed_values"]["0"] += 1
        summary_path.write_text(json.dumps(payload), encoding="utf-8")
        write_inventory(self.summary_root, [summary_path, self.summary_root / "audit.json"])
        with self.assertRaises(SystemExit):
            MODULE.load_one_summary(
                self.summary_root, self.identity_path, self.matrix, self.catalog
            )

    def test_v2_template_is_result_free_and_exact_schema(self) -> None:
        path = ROOT / "comparisons/reproduced-results.v2.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, MODULE.FIELDS)
            self.assertEqual(list(reader), [])


if __name__ == "__main__":
    unittest.main()
