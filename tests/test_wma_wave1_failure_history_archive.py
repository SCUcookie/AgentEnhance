from __future__ import annotations

import hashlib
import importlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


class Wave1FailureHistoryArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = importlib.import_module("remote_archive_wma_wave1_failure_history")

    @staticmethod
    def write_inventory(root: Path, name: str, member: Path) -> None:
        digest = hashlib.sha256(member.read_bytes()).hexdigest()
        (root / name).write_text(f"{digest}  {member}\n", encoding="utf-8")

    def make_sources(self, base: Path) -> dict[str, Path]:
        roots = {name: base / name for name in self.module.SOURCE_ROOTS}
        for root in roots.values():
            root.mkdir(parents=True)
        for key in ("initial_controller_rejection", "recovery1_controller_rejection"):
            (roots[key] / "TERMINAL_REJECTED").touch()
        failed = roots["recovery1_failed_seed"]
        (failed / "SCHEDULER_EXECUTION_WITH_REJECTIONS").touch()
        for index in range(71):
            unit = failed / "units" / f"{index:03d}"
            unit.mkdir(parents=True)
            (unit / "TERMINAL_ACCEPTED").touch()
        rejected = failed / "units" / "071_rejected"
        rejected.mkdir(parents=True)
        (rejected / "TERMINAL_REJECTED").touch()
        self.write_inventory(
            failed,
            "SCHEDULER_SHA256SUMS",
            failed / "SCHEDULER_EXECUTION_WITH_REJECTIONS",
        )
        wrong = roots["recovery2_wrong_path_capability"]
        (wrong / "TERMINAL_REJECTED").touch()
        capability = roots["recovery2_accepted_capability"]
        (capability / "TERMINAL_ACCEPTED").touch()
        audit = capability / "audit.json"
        audit.write_text("{}\n", encoding="utf-8")
        self.write_inventory(capability, "SHA256SUMS", audit)
        return roots

    def test_exact_source_states_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.module.SOURCE_ROOTS = self.make_sources(Path(directory))
            records = self.module.validate_sources()
            self.assertEqual(set(records), set(self.module.SOURCE_ROOTS))
            self.assertEqual(records["recovery1_failed_seed"]["regular_files"], 74)
            self.assertTrue(all(len(row["tree_sha256"]) == 64 for row in records.values()))

    def test_partial_failed_seed_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            roots = self.make_sources(Path(directory))
            (roots["recovery1_failed_seed"] / "units/000/TERMINAL_ACCEPTED").unlink()
            self.module.SOURCE_ROOTS = roots
            with self.assertRaises(RuntimeError):
                self.module.validate_sources()

    def test_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("evidence", encoding="utf-8")
            (root / "link").symlink_to(target)
            with self.assertRaises(RuntimeError):
                self.module.scan_root(root)


if __name__ == "__main__":
    unittest.main()
