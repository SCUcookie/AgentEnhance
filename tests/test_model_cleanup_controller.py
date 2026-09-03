from __future__ import annotations

import hashlib
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


class ModelCleanupControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = importlib.import_module("model_cleanup_controller")

    @staticmethod
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def inventory(self, root: Path, name: str, members: list[Path]) -> Path:
        path = root / name
        path.write_text(
            "".join(f"{self.sha(member)}  {member}\n" for member in members),
            encoding="utf-8",
        )
        return path

    def terminal_root(self, root: Path, extra: dict[str, object] | None = None) -> tuple[Path, Path]:
        root.mkdir(parents=True)
        member = root / "payload.json"
        member.write_text(json.dumps(extra or {}) + "\n", encoding="utf-8")
        inventory = self.inventory(root, "SHA256SUMS", [member])
        (root / "TERMINAL_ACCEPTED").touch()
        return root, inventory

    def build_fixture(self, base: Path) -> tuple[Path, Path, Path]:
        base = base.resolve()
        model_parent = base / "AgentEnhance/cache/models"
        record_parent = base / "AgentEnhance/runs/model-cleanup"
        model_parent.mkdir(parents=True)
        record_parent.mkdir(parents=True)
        self.module.ELIGIBLE_PREFIXES = (model_parent,)
        self.module.RECORD_PREFIXES = (record_parent,)
        target = model_parent / "test-model"
        target.mkdir()
        weight = target / "model.bin"
        weight.write_bytes(b"model-weights")
        quarantine = model_parent / "test-model.agentenhance-quarantine-unit"

        policy = base / "policy.json"
        policy.write_text(
            json.dumps({"status": "FROZEN_BEFORE_ANY_MODEL_CLEANUP"}) + "\n",
            encoding="utf-8",
        )
        ledger = base / "ledger.json"
        ledger.write_text(
            json.dumps(
                {
                    "protected_shared_assets": [
                        {"repository": "shared/model", "revision": "f" * 40}
                    ],
                    "project_owned_candidates": [
                        {
                            "model_id": "test",
                            "repository": "owner/model",
                            "revision": "a" * 40,
                            "target": "${AGENT_ENHANCE_REMOTE_ROOT}/cache/models/test-model",
                            "expected_files": 1,
                            "expected_bytes": len(b"model-weights"),
                            "required_dependents": ["wma-test"],
                            "conservative_endpoint_dependents": [],
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        materialization_root = base / "materialization"
        materialization_root.mkdir()
        materialization = materialization_root / "model-materialization.json"
        materialization.write_text(
            json.dumps(
                {
                    "status": "TERMINAL_ACCEPTED",
                    "repository": "owner/model",
                    "revision": "a" * 40,
                    "target": str(target),
                    "file_count": 1,
                    "total_bytes": len(b"model-weights"),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        model_inventory = self.inventory(materialization_root, "MODEL_SHA256SUMS", [weight])
        repository_audit = base / "repository-access.json"
        repository_audit.write_text(
            json.dumps(
                {
                    "status": "IMMUTABLE_REVISION_ACCESSIBLE",
                    "repository": "owner/model",
                    "revision": "a" * 40,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        lifecycle, lifecycle_inventory = self.terminal_root(base / "lifecycle")
        summary_payload = {
            "status": "TERMINAL_ACCEPTED",
            "main_comparison_eligible": True,
            "implementation_id": "wma-test",
            "seed_count": 3,
            "seeds": [0, 1, 2],
            "n_samples": 150,
            "n_qa": 7906,
        }
        summary = base / "summary"
        summary.mkdir()
        summary_member = summary / "method-seed-summary.json"
        summary_member.write_text(json.dumps(summary_payload) + "\n", encoding="utf-8")
        summary_inventory = self.inventory(summary, "SHA256SUMS", [summary_member])
        (summary / "TERMINAL_ACCEPTED").touch()
        archive, archive_inventory = self.terminal_root(base / "archive")
        eligibility = base / "eligibility.json"
        eligibility.write_text(
            json.dumps(
                {
                    "status": "DRY_RUN_ELIGIBLE",
                    "model_id": "test",
                    "repository": "owner/model",
                    "revision": "a" * 40,
                    "target": str(target),
                    "quarantine": str(quarantine),
                    "policy": {"path": str(policy), "sha256": self.sha(policy)},
                    "ownership_ledger": {"path": str(ledger), "sha256": self.sha(ledger)},
                    "materialization": {
                        "record": str(materialization),
                        "record_sha256": self.sha(materialization),
                        "model_inventory": str(model_inventory),
                        "model_inventory_sha256": self.sha(model_inventory),
                    },
                    "repository_access_audit": {
                        "path": str(repository_audit),
                        "sha256": self.sha(repository_audit),
                    },
                    "dependent_evidence": [
                        {
                            "implementation_id": "wma-test",
                            "lifecycle": {
                                "root": str(lifecycle),
                                "inventory": str(lifecycle_inventory),
                                "inventory_sha256": self.sha(lifecycle_inventory),
                            },
                            "summary": {
                                "root": str(summary),
                                "inventory": str(summary_inventory),
                                "inventory_sha256": self.sha(summary_inventory),
                            },
                            "archive": {
                                "root": str(archive),
                                "inventory": str(archive_inventory),
                                "inventory_sha256": self.sha(archive_inventory),
                            },
                        }
                    ],
                    "pre_cleanup": self.module.scan_tree(target),
                    "project_reference_audit": "ONLY_RETIRED_ACCEPTED_DEPENDENTS",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return eligibility, target, quarantine

    @mock.patch("model_cleanup_controller.subprocess.run")
    def test_preflight_is_read_only(self, run: mock.Mock) -> None:
        run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            eligibility, target, quarantine = self.build_fixture(Path(directory))
            self.assertEqual(self.module.preflight(eligibility), 0)
            self.assertTrue(target.is_dir())
            self.assertFalse(quarantine.exists())

    @mock.patch("model_cleanup_controller.subprocess.run")
    def test_quarantine_then_exact_delete_preserves_evidence(self, run: mock.Mock) -> None:
        run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            eligibility, target, quarantine = self.build_fixture(base)
            phase1 = base / "AgentEnhance/runs/model-cleanup/test/phase1.json"
            phase2 = base / "AgentEnhance/runs/model-cleanup/test/phase2.json"
            self.assertEqual(self.module.quarantine(eligibility, phase1), 0)
            self.assertFalse(target.exists())
            self.assertTrue(quarantine.is_dir())
            self.assertEqual(self.module.delete_quarantine(phase1, phase2), 0)
            self.assertFalse(target.exists())
            self.assertFalse(quarantine.exists())
            self.assertEqual(json.loads(phase2.read_text())["status"], "DELETED")
            self.assertTrue((base / "archive/TERMINAL_ACCEPTED").is_file())

    @mock.patch("model_cleanup_controller.subprocess.run")
    def test_active_process_reference_rejects_before_mutation(self, run: mock.Mock) -> None:
        run.return_value = SimpleNamespace(returncode=0, stdout="COMMAND PID\n", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            eligibility, target, quarantine = self.build_fixture(Path(directory))
            with self.assertRaises(RuntimeError):
                self.module.preflight(eligibility)
            self.assertTrue(target.is_dir())
            self.assertFalse(quarantine.exists())

    def test_target_must_be_exact_child_and_not_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            eligible = base / "AgentEnhance/cache/models"
            eligible.mkdir(parents=True)
            self.module.ELIGIBLE_PREFIXES = (eligible,)
            nested = eligible / "group/model"
            nested.mkdir(parents=True)
            with self.assertRaises(RuntimeError):
                self.module.validate_exact_target(nested)
            real = eligible / "real"
            real.mkdir()
            link = eligible / "link"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                self.module.validate_exact_target(link)


if __name__ == "__main__":
    unittest.main()
