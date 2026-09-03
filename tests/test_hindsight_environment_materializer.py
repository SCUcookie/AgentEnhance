from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from pip._vendor.packaging.markers import default_environment
from pip._vendor.packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_hindsight_environment.py"
SPEC = importlib.util.spec_from_file_location("materialize_hindsight_environment", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HindsightEnvironmentMaterializerTest(unittest.TestCase):
    def test_install_command_is_strictly_offline_and_hash_enforced(self) -> None:
        command = MODULE.install_command(
            Path("/environment/bin/python"), Path("/routing"), Path("/wheelhouse")
        )
        for flag in (
            "--isolated",
            "--no-cache-dir",
            "--no-index",
            "--no-deps",
            "--require-hashes",
            "--only-binary=:all:",
        ):
            self.assertIn(flag, command)
        self.assertNotIn("--index-url", command)
        self.assertNotIn("--extra-index-url", command)
        self.assertEqual(command.count("--find-links"), 2)
        self.assertEqual(command.count("--requirement"), 2)

    def test_active_requirements_apply_target_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements.txt"
            path.write_text(
                "alpha==1.2 \\\n    --hash=sha256:" + "a" * 64 + "\n"
                "beta==2.0 ; sys_platform == 'never' \\\n    --hash=sha256:" + "b" * 64 + "\n",
                encoding="utf-8",
            )
            active = MODULE.active_requirements(
                [path], Requirement, default_environment()
            )
        self.assertEqual(set(active), {"alpha"})
        self.assertTrue(active["alpha"].specifier.contains("1.2"))

    def test_expected_distribution_count_is_frozen(self) -> None:
        self.assertEqual(MODULE.EXPECTED_ACTIVE, 199)
        self.assertEqual(sum(row["active"] for row in MODULE.ROUTES.values()), 199)


if __name__ == "__main__":
    unittest.main()
