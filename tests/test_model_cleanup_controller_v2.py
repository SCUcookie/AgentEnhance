from __future__ import annotations

import hashlib
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class ModelCleanupControllerV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = importlib.import_module("model_cleanup_controller_v2")

    @staticmethod
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def terminal_archive(self, root: Path) -> dict:
        root.mkdir()
        payload = root / "payload.json"
        payload.write_text("{}\n", encoding="utf-8")
        inventory = root / "SHA256SUMS"
        inventory.write_text(f"{self.sha(payload)}  {payload}\n", encoding="utf-8")
        (root / "TERMINAL_ACCEPTED").touch()
        return {"root": str(root), "inventory": str(inventory), "inventory_sha256": self.sha(inventory)}

    def completion(self, base: Path, official_values_used: bool = False) -> Path:
        root = base / "completion"
        root.mkdir()
        tracks = []
        for index, (track_id, methods) in enumerate(self.module.EXPECTED_METHODS.items()):
            ordered = sorted(methods)
            tracks.append(
                {
                    "track_id": track_id,
                    "status": "TERMINAL_ACCEPTED_COMPLETE_SURFACE",
                    "registered_methods": ordered,
                    "accepted_methods": ordered[:-1],
                    "terminal_blocked_or_failed_methods": ordered[-1:],
                    "official_values_used": False,
                    "denominator_reconciled": True,
                    "archive": self.terminal_archive(base / f"archive-{index}"),
                }
            )
        record = root / "cross-track-completion.json"
        record.write_text(
            json.dumps(
                {
                    "status": "TERMINAL_ACCEPTED_COMPLETE_SURFACE",
                    "global_contract": self.module.GLOBAL_COMPLETION_CONTRACT,
                    "wma_table_spec": self.module.WMA_TABLE_SPEC,
                    "official_values_used": official_values_used,
                    "all_accepted_and_rejected_evidence_archived": True,
                    "all_denominators_reconciled": True,
                    "tracks": tracks,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        inventory = root / "EVIDENCE_SHA256SUMS"
        inventory.write_text(f"{self.sha(record)}  {record}\n", encoding="utf-8")
        (root / "TERMINAL_ACCEPTED").touch()
        return record

    def test_missing_global_completion_blocks_before_old_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing" / "cross-track-completion.json"
            with mock.patch.object(self.module, "GLOBAL_COMPLETION_RECORD", missing), mock.patch.object(
                self.module.base, "preflight"
            ) as old_preflight:
                with self.assertRaisesRegex(RuntimeError, "not terminal-accepted"):
                    self.module.preflight(Path(directory) / "eligibility.json")
                old_preflight.assert_not_called()

    def test_complete_three_track_surface_allows_delegation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record = self.completion(Path(directory))
            with mock.patch.object(self.module, "GLOBAL_COMPLETION_RECORD", record), mock.patch.object(
                self.module.base, "preflight", return_value=0
            ) as old_preflight:
                self.assertEqual(self.module.preflight(Path(directory) / "eligibility.json"), 0)
                old_preflight.assert_called_once()

    def test_official_value_contamination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record = self.completion(Path(directory), official_values_used=True)
            with self.assertRaisesRegex(RuntimeError, "official values"):
                self.module.validate_global_completion(record)


if __name__ == "__main__":
    unittest.main()
