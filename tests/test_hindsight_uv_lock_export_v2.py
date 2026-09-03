from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "export_hindsight_uv_lock_v2.py"
SPEC = importlib.util.spec_from_file_location("export_hindsight_uv_lock_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HindsightUvLockExportV2Test(unittest.TestCase):
    def test_recovery_expectations_are_frozen(self) -> None:
        self.assertEqual(MODULE.EXPECTED_BODY_BYTES, 256_006)
        self.assertEqual(len(MODULE.EXPECTED_BODY_SHA256), 64)
        self.assertEqual(MODULE.EXPECTED_REQUIREMENT_HEAD_COUNT, 208)

    def test_normalization_removes_only_validated_header(self) -> None:
        first = MODULE.HEADER_LINE
        second = MODULE.COMMAND_PREFIX + b"--output-file a\n"
        body = b"aiohttp==1.0 \\\n    --hash=sha256:abc\n"
        self.assertEqual(MODULE.normalized_body(first + second + body), body)

    def test_normalization_rejects_unknown_header(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "header"):
            MODULE.normalized_body(b"# unknown\n# command\naiohttp==1\n")


if __name__ == "__main__":
    unittest.main()
