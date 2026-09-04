from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import audit_wma_wave1_release_gate as gate  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_sums(root: Path, members: list[Path], inventory_name: str = "SHA256SUMS") -> None:
    (root / inventory_name).write_text(
        "".join(f"{sha256(path)}  {path}\n" for path in members),
        encoding="utf-8",
    )


class Wave1ReleaseGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.run_base = self.base / "runs"
        self.run_base.mkdir()
        self.controller = self.run_base / gate.CONTROLLER_NAME
        self.controller.mkdir()
        self.inventory = self.base / "units.csv"
        with self.inventory.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("sample_index", "sample_id", "relative_json_path", "sessions", "turns", "attachments", "qa", "source_json_sha256"),
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows([
                {"sample_index": 1, "sample_id": "alpha", "relative_json_path": "a.json", "sessions": 1, "turns": 2, "attachments": 0, "qa": 1, "source_json_sha256": "0" * 64},
                {"sample_index": 2, "sample_id": "beta", "relative_json_path": "b.json", "sessions": 1, "turns": 2, "attachments": 0, "qa": 2, "source_json_sha256": "1" * 64},
            ])
        self.patchers = (
            mock.patch.object(gate, "EXPECTED_UNITS", 2),
            mock.patch.object(gate, "EXPECTED_SESSIONS", 2),
            mock.patch.object(gate, "EXPECTED_QA", 3),
            mock.patch.object(gate, "UNIT_INVENTORY_SHA256", sha256(self.inventory)),
        )
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self._build_accepted_surface()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _build_accepted_surface(self) -> None:
        identity = self.controller / "identity.txt"
        identity.write_text(
            "\n".join([
                "started_at=2026-09-04T05:40:48+08:00",
                f"methods={','.join(gate.METHODS)}",
                "seeds=0,1,2",
                f"package_root={gate.PACKAGE_ROOT}",
                f"package_manifest_sha256={gate.PACKAGE_MANIFEST_SHA256}",
                "recovery_controller=remote_wma_wave1_controller_recovery2.sh",
                f"recovery_full_scheduler_sha256={gate.RECOVERY_FULL_SCHEDULER_SHA256}",
                "chat_gpu_memory_utilization=0.90",
                "parent_evidence_reused=false",
                "",
            ]),
            encoding="utf-8",
        )
        progress = self.controller / "progress.csv"
        with progress.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("method", "seed", "run_id", "scheduler_status", "aggregate_status", "finished_at"),
                lineterminator="\n",
            )
            writer.writeheader()
            for method, seed, run_id in gate.expected_progress():
                writer.writerow({
                    "method": method,
                    "seed": seed,
                    "run_id": run_id,
                    "scheduler_status": "ACCEPTED",
                    "aggregate_status": "ACCEPTED",
                    "finished_at": "2026-09-04T06:00:00+08:00",
                })
                run_root = self.run_base / run_id
                units = run_root / "units"
                units.mkdir(parents=True)
                progress_path = run_root / "progress.txt"
                progress_path.write_text("accepted=2\nrejected=0\n", encoding="utf-8")
                rejected_path = run_root / "rejected-units.csv"
                rejected_path.write_text("sample_index,sample_id,unit_root,reason\n", encoding="utf-8")
                log_path = run_root / "scheduler.log"
                log_path.write_text("synthetic scheduler\n", encoding="utf-8")
                summary_path = run_root / "scheduler-summary.txt"
                summary_path.write_text(
                    "accepted=2\nrejected=0\ninfrastructure_failure=0\nfinished_at=2026-09-04T06:00:00+08:00\n",
                    encoding="utf-8",
                )
                scheduler_members = [progress_path, rejected_path, log_path, summary_path]
                for unit_name in ("001_alpha", "002_beta"):
                    unit = units / unit_name
                    unit.mkdir()
                    payload = unit / "payload.txt"
                    payload.write_text(f"{run_id}:{unit_name}\n", encoding="utf-8")
                    write_sums(unit, [payload])
                    (unit / "TERMINAL_ACCEPTED").touch()
                    scheduler_members.extend((payload, unit / "SHA256SUMS", unit / "TERMINAL_ACCEPTED"))
                write_sums(run_root, scheduler_members, "SCHEDULER_SHA256SUMS")
                (run_root / "SCHEDULER_EXECUTION_ACCEPTED").touch()
                aggregate = self.run_base / f"{run_id}-aggregate"
                aggregate.mkdir()
                audit = aggregate / "audit.json"
                audit.write_text(json.dumps({
                    "status": "TERMINAL_ACCEPTED",
                    "baseline": method,
                    "seed": seed,
                    "n_expected": 2,
                    "n_observed": 2,
                    "n_failed": 0,
                    "n_sessions": 2,
                    "n_qa": 3,
                    "main_comparison_eligible": True,
                    "inventory_sha256": sha256(self.inventory),
                    "source_commit": gate.WMA_SOURCE_COMMIT,
                    "dataset_manifest_sha256": gate.DATASET_MANIFEST_SHA256,
                }) + "\n", encoding="utf-8")
                write_sums(aggregate, [audit])
                (aggregate / "TERMINAL_ACCEPTED").touch()
        write_sums(self.controller, [identity, progress])
        (self.controller / "TERMINAL_ACCEPTED").touch()

    def audit(self, **overrides: object) -> dict[str, object]:
        args: dict[str, object] = {
            "controller_root": self.controller,
            "run_base": self.run_base,
            "unit_inventory": self.inventory,
            "future_roots": [self.base / "future"],
            "command_lines": [],
            "observed_ports": set(),
            "observed_tmux_sessions": [],
            "data1_free_bytes": 50 * 1024**3,
            "data2_free_bytes": 50 * 1024**3,
        }
        args.update(overrides)
        return gate.audit_release(**args)  # type: ignore[arg-type]

    def test_complete_release_surface_is_accepted_without_scores_or_mutation(self) -> None:
        report = self.audit()
        self.assertEqual(report["status"], "TERMINAL_ACCEPTED")
        self.assertEqual(report["method_seed_runs"], 12)
        self.assertEqual(report["accepted_units"], 24)
        self.assertEqual(report["accepted_qa"], 36)
        self.assertEqual(report["scores_observed"], 0)
        self.assertFalse(report["mutation_performed"])

    def test_controller_must_be_terminal_accepted(self) -> None:
        (self.controller / "TERMINAL_ACCEPTED").unlink()
        with self.assertRaisesRegex(RuntimeError, "controller is not terminal accepted"):
            self.audit()

    def test_every_unit_inventory_is_rehashed(self) -> None:
        run_id = gate.expected_progress()[0][2]
        payload = self.run_base / run_id / "units/001_alpha/payload.txt"
        payload.write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "inventory digest mismatch"):
            self.audit()

    def test_active_process_port_or_tmux_fails_closed(self) -> None:
        cases = (
            {"command_lines": ["python remote_wma_full_method_recovery2.sh"]},
            {"observed_ports": {18120}},
            {"observed_tmux_sessions": ["agentenhance-wma-wave1-controller-r2-v1"]},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(RuntimeError):
                self.audit(**overrides)

    def test_future_root_collision_or_storage_shortfall_fails_closed(self) -> None:
        future = self.base / "collision"
        future.mkdir()
        cases = (
            {"future_roots": [future]},
            {"data1_free_bytes": 39 * 1024**3},
            {"data2_free_bytes": 1},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(RuntimeError):
                self.audit(**overrides)


if __name__ == "__main__":
    unittest.main()
