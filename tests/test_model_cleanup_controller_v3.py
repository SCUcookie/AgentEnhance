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
sys.path.insert(0, str(ROOT / "scripts"))


class ModelCleanupControllerV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = importlib.import_module("model_cleanup_controller_v3")

    @staticmethod
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def inventory(self, root: Path, name: str, members: list[Path]) -> Path:
        path = root / name
        path.write_text("".join(f"{self.sha(member)}  {member}\n" for member in members), encoding="utf-8")
        return path

    def terminal_payload(self, root: Path, filename: str, payload: dict) -> dict:
        root.mkdir(parents=True)
        member = root / filename
        member.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        inventory = self.inventory(root, "SHA256SUMS", [member])
        (root / "TERMINAL_ACCEPTED").touch()
        return {"root": str(root), "inventory": str(inventory), "inventory_sha256": self.sha(inventory)}

    def build_global_completion(self, base: Path) -> tuple[Path, dict]:
        root = base / "completion"
        root.mkdir()
        tracks = []
        for index, (track_id, methods) in enumerate(self.module.cross_track.EXPECTED_METHODS.items()):
            archive = self.terminal_payload(base / f"track-archive-{index}", "archive.json", {"track_id": track_id})
            ordered = sorted(methods)
            tracks.append({
                "track_id": track_id,
                "status": "TERMINAL_ACCEPTED_COMPLETE_SURFACE",
                "registered_methods": ordered,
                "accepted_methods": ordered,
                "terminal_blocked_or_failed_methods": [],
                "official_values_used": False,
                "denominator_reconciled": True,
                "archive": archive,
            })
        payload = {
            "status": "TERMINAL_ACCEPTED_COMPLETE_SURFACE",
            "global_contract": self.module.cross_track.GLOBAL_COMPLETION_CONTRACT,
            "wma_table_spec": self.module.cross_track.WMA_TABLE_SPEC,
            "official_values_used": False,
            "all_accepted_and_rejected_evidence_archived": True,
            "all_denominators_reconciled": True,
            "tracks": tracks,
        }
        record = root / "cross-track-completion.json"
        record.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        self.inventory(root, "EVIDENCE_SHA256SUMS", [record])
        (root / "TERMINAL_ACCEPTED").touch()
        return record, payload

    def rewrite_terminal_payload(self, entry: dict, filename: str, payload: dict) -> None:
        root = Path(entry["root"])
        member = root / filename
        member.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        inventory = Path(entry["inventory"])
        inventory.write_text(f"{self.sha(member)}  {member}\n", encoding="utf-8")
        entry["inventory_sha256"] = self.sha(inventory)

    def build_fixture(self, base: Path) -> tuple[Path, Path, Path, dict]:
        base = base.resolve()
        model_parent = base / "AgentEnhance/cache/models"
        record_parent = base / "AgentEnhance/runs/model-cleanup"
        model_parent.mkdir(parents=True)
        record_parent.mkdir(parents=True)
        self.module.base.ELIGIBLE_PREFIXES = (model_parent,)
        self.module.base.RECORD_PREFIXES = (record_parent,)
        target = model_parent / "test-model"
        target.mkdir()
        weight = target / "model.bin"
        weight.write_bytes(b"model-weights")
        quarantine = model_parent / "test-model.agentenhance-quarantine-unit"

        policy = base / "policy.json"
        policy.write_text(json.dumps({"status": "FROZEN_BEFORE_ANY_MODEL_CLEANUP"}) + "\n", encoding="utf-8")
        self.module.POLICY_SHA256 = self.sha(policy)

        ledger_v1 = base / "ledger-v1.json"
        ledger_v1_payload = {
            "schema_version": "agentenhance.baseline_model_ownership_ledger.v1",
            "protected_shared_assets": [{"repository": "shared/model", "revision": "f" * 40}],
            "project_owned_candidates": [{
                "model_id": "test",
                "repository": "owner/model",
                "revision": "a" * 40,
                "target": "${AGENT_ENHANCE_REMOTE_ROOT}/cache/models/test-model",
                "expected_files": 1,
                "expected_bytes": len(b"model-weights"),
                "required_dependents": ["wma-mmfu-single"],
                "conservative_endpoint_dependents": [],
            }],
        }
        ledger_v1.write_text(json.dumps(ledger_v1_payload, sort_keys=True) + "\n", encoding="utf-8")
        self.module.LEDGER_V1_SHA256 = self.sha(ledger_v1)
        ledger_v2 = base / "ledger-v2.json"
        ledger_v2.write_text(json.dumps({
            "schema_version": "agentenhance.baseline_model_ownership_ledger.v2",
            "supersedes": {"sha256": self.sha(ledger_v1)},
            "expanded_project_owned_dependents": [{
                "model_id": "test",
                "repository": "owner/model",
                "revision": "a" * 40,
                "target": "${AGENT_ENHANCE_REMOTE_ROOT}/cache/models/test-model",
                "inherited_required_dependents": ["wma-mmfu-single"],
                "inherited_conservative_endpoint_dependents": [],
                "new_required_dependents": ["memgallery-a-mem"],
            }],
            "new_project_owned_candidates": [],
        }, sort_keys=True) + "\n", encoding="utf-8")
        self.module.LEDGER_V2_SHA256 = self.sha(ledger_v2)

        completion, completion_payload = self.build_global_completion(base)
        self.module.GLOBAL_COMPLETION_RECORD = completion
        completion_sha = self.sha(completion)
        track_map = {row["track_id"]: row for row in completion_payload["tracks"]}
        dependents = {
            (self.module.TRACK_WMA, "wma-mmfu-single"),
            (self.module.TRACK_MEMGALLERY, "a-mem"),
        }
        retirements = []
        for index, (track_id, method_id) in enumerate(sorted(dependents)):
            receipt = self.terminal_payload(base / f"retirement-{index}", "dependent-retirement.json", {
                "schema_version": "agentenhance.model_dependency_retirement.v1",
                "status": "TERMINAL_ACCEPTED_RETIRED",
                "track_id": track_id,
                "method_id": method_id,
                "outcome": "ACCEPTED",
                "global_completion_sha256": completion_sha,
                "track_archive": track_map[track_id]["archive"],
                "official_values_used": False,
                "pending_runs": 0,
                "active_process_references": 0,
                "model_reference_retired": True,
            })
            retirements.append({"track_id": track_id, "method_id": method_id, "receipt": receipt})

        reference = self.terminal_payload(base / "reference-audit", "project-reference-audit.json", {
            "status": "TERMINAL_ACCEPTED_NO_ACTIVE_OR_PENDING_REFERENCES",
            "model_id": "test",
            "target": str(target),
            "global_completion_sha256": completion_sha,
            "registered_dependents": [
                {"track_id": track_id, "method_id": method_id}
                for track_id, method_id in sorted(dependents)
            ],
            "active_process_references": [],
            "pending_run_references": [],
            "datasets_results_logs_archives_retained": True,
        })

        materialization_root = base / "materialization"
        materialization_root.mkdir()
        materialization = materialization_root / "model-materialization.json"
        materialization.write_text(json.dumps({
            "status": "TERMINAL_ACCEPTED",
            "repository": "owner/model",
            "revision": "a" * 40,
            "target": str(target),
            "file_count": 1,
            "total_bytes": len(b"model-weights"),
        }) + "\n", encoding="utf-8")
        model_inventory = self.inventory(materialization_root, "MODEL_SHA256SUMS", [weight])
        repository_audit = base / "repository-access.json"
        repository_audit.write_text(json.dumps({
            "status": "IMMUTABLE_REVISION_ACCESSIBLE",
            "repository": "owner/model",
            "revision": "a" * 40,
        }) + "\n", encoding="utf-8")

        eligibility_payload = {
            "status": "DRY_RUN_ELIGIBLE_V3",
            "model_id": "test",
            "repository": "owner/model",
            "revision": "a" * 40,
            "target": str(target),
            "quarantine": str(quarantine),
            "policy": {"path": str(policy), "sha256": self.sha(policy)},
            "ownership_ledger_v1": {"path": str(ledger_v1), "sha256": self.sha(ledger_v1)},
            "ownership_ledger_v2": {"path": str(ledger_v2), "sha256": self.sha(ledger_v2)},
            "materialization": {
                "record": str(materialization),
                "record_sha256": self.sha(materialization),
                "model_inventory": str(model_inventory),
                "model_inventory_sha256": self.sha(model_inventory),
            },
            "repository_access_audit": {"path": str(repository_audit), "sha256": self.sha(repository_audit)},
            "dependent_retirements": retirements,
            "project_reference_audit": reference,
            "pre_cleanup": self.module.base.scan_tree(target),
        }
        eligibility = base / "eligibility.json"
        eligibility.write_text(json.dumps(eligibility_payload, sort_keys=True) + "\n", encoding="utf-8")
        return eligibility, target, quarantine, eligibility_payload

    @mock.patch("model_cleanup_controller.subprocess.run")
    def test_preflight_is_read_only_after_v2_dependency_merge(self, run: mock.Mock) -> None:
        run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            eligibility, target, quarantine, _ = self.build_fixture(Path(directory))
            self.assertEqual(self.module.preflight(eligibility), 0)
            self.assertTrue(target.is_dir())
            self.assertFalse(quarantine.exists())

    @mock.patch("model_cleanup_controller.subprocess.run")
    def test_missing_global_completion_blocks_without_mutation(self, run: mock.Mock) -> None:
        run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            eligibility, target, quarantine, _ = self.build_fixture(Path(directory))
            (self.module.GLOBAL_COMPLETION_RECORD.parent / "TERMINAL_ACCEPTED").unlink()
            with self.assertRaisesRegex(RuntimeError, "not terminal-accepted"):
                self.module.preflight(eligibility)
            self.assertTrue(target.is_dir())
            self.assertFalse(quarantine.exists())

    @mock.patch("model_cleanup_controller.subprocess.run")
    def test_v2_added_dependent_cannot_be_omitted(self, run: mock.Mock) -> None:
        run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            eligibility, target, _, payload = self.build_fixture(Path(directory))
            payload["dependent_retirements"] = payload["dependent_retirements"][:1]
            eligibility.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "exactly cover effective ownership"):
                self.module.preflight(eligibility)
            self.assertTrue(target.is_dir())

    @mock.patch("model_cleanup_controller.subprocess.run")
    def test_live_project_reference_rejects_before_mutation(self, run: mock.Mock) -> None:
        run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            eligibility, target, _, payload = self.build_fixture(Path(directory))
            entry = payload["project_reference_audit"]
            audit_path = Path(entry["root"]) / "project-reference-audit.json"
            audit = json.loads(audit_path.read_text())
            audit["pending_run_references"] = ["future-run"]
            self.rewrite_terminal_payload(entry, "project-reference-audit.json", audit)
            eligibility.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "found live references"):
                self.module.preflight(eligibility)
            self.assertTrue(target.is_dir())

    @mock.patch("model_cleanup_controller.subprocess.run")
    def test_quarantine_and_delete_only_weight_root_preserve_evidence(self, run: mock.Mock) -> None:
        run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            eligibility, target, quarantine, payload = self.build_fixture(base)
            phase1 = base / "AgentEnhance/runs/model-cleanup/test/phase1.json"
            phase2 = base / "AgentEnhance/runs/model-cleanup/test/phase2.json"
            self.assertEqual(self.module.quarantine(eligibility, phase1), 0)
            self.assertFalse(target.exists())
            self.assertTrue(quarantine.is_dir())
            self.assertEqual(self.module.delete_quarantine(phase1, phase2), 0)
            self.assertFalse(target.exists())
            self.assertFalse(quarantine.exists())
            self.assertEqual(json.loads(phase2.read_text())["status"], "DELETED_V3")
            self.assertTrue(Path(payload["project_reference_audit"]["root"]).is_dir())
            self.assertTrue(self.module.GLOBAL_COMPLETION_RECORD.is_file())

    @mock.patch("model_cleanup_controller.subprocess.run")
    def test_active_open_file_reference_rejects_before_mutation(self, run: mock.Mock) -> None:
        run.return_value = SimpleNamespace(returncode=0, stdout="COMMAND PID\n", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            eligibility, target, quarantine, _ = self.build_fixture(Path(directory))
            with self.assertRaisesRegex(RuntimeError, "active process references"):
                self.module.preflight(eligibility)
            self.assertTrue(target.is_dir())
            self.assertFalse(quarantine.exists())


if __name__ == "__main__":
    unittest.main()
