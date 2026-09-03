from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from pip._vendor.packaging.markers import default_environment
from pip._vendor.packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_hindsight_wheelhouse.py"
SPEC = importlib.util.spec_from_file_location("audit_hindsight_wheelhouse", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HindsightWheelhouseAuditTest(unittest.TestCase):
    def test_requirement_blocks_apply_markers_and_keep_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements.txt"
            path.write_text(
                "alpha==1.0 \\\n    --hash=sha256:" + "a" * 64 + "\n"
                "beta==2.0 ; sys_platform == 'never' \\\n    --hash=sha256:" + "b" * 64 + "\n",
                encoding="utf-8",
            )
            blocks = MODULE.requirement_blocks(path, Requirement, default_environment())
        self.assertEqual(set(blocks), {"alpha"})
        self.assertEqual(blocks["alpha"]["hashes"], {"a" * 64})

    def test_download_commands_reject_extra_index(self) -> None:
        commands = []
        for route in MODULE.ROUTES.values():
            commands.append(
                [
                    "python",
                    "-m",
                    "pip",
                    "download",
                    "--isolated",
                    "--no-cache-dir",
                    "--no-deps",
                    "--require-hashes",
                    "--only-binary=:all:",
                    "--retries",
                    "0",
                    "--index-url",
                    route["url"],
                ]
            )
        MODULE.validate_download_commands(commands)
        commands[0].extend(["--extra-index-url", "https://invalid.example"])
        with self.assertRaisesRegex(RuntimeError, "extra index"):
            MODULE.validate_download_commands(commands)

    def test_expected_cardinality_and_ceiling_are_frozen(self) -> None:
        self.assertEqual(MODULE.EXPECTED_WHEELS, 199)
        self.assertEqual(sum(row["active"] for row in MODULE.ROUTES.values()), 199)
        self.assertEqual(MODULE.BYTE_CEILING, 6 * 1024**3)


if __name__ == "__main__":
    unittest.main()
