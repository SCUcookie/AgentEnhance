from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_hindsight_wheelhouse.py"
SPEC = importlib.util.spec_from_file_location("materialize_hindsight_wheelhouse", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HindsightWheelhouseMaterializerTest(unittest.TestCase):
    def test_download_command_is_single_source_hash_enforced(self) -> None:
        command = MODULE.download_command(
            Path("/python"), Path("/requirements"), Path("/wheelhouse"), "https://pypi.org/simple"
        )
        for flag in (
            "--isolated",
            "--no-cache-dir",
            "--no-deps",
            "--require-hashes",
            "--only-binary=:all:",
        ):
            self.assertIn(flag, command)
        self.assertNotIn("--extra-index-url", command)
        self.assertEqual(command[command.index("--retries") + 1], "0")
        self.assertEqual(command[command.index("--index-url") + 1], "https://pypi.org/simple")

    def test_routes_and_cardinality_are_frozen(self) -> None:
        self.assertEqual(MODULE.EXPECTED_ACTIVE_TOTAL, 199)
        self.assertEqual(MODULE.ROUTES["pypi"]["active_requirements"], 198)
        self.assertEqual(MODULE.ROUTES["pytorch-cpu"]["active_requirements"], 1)
        self.assertEqual(
            MODULE.ROUTES["pytorch-cpu"]["url"],
            "https://download.pytorch.org/whl/cpu",
        )

    def test_resource_ceiling_is_six_gib(self) -> None:
        self.assertEqual(MODULE.BYTE_CEILING, 6 * 1024**3)


if __name__ == "__main__":
    unittest.main()
