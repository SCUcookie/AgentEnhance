from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "export_hindsight_uv_lock_v3.py"
SPEC = importlib.util.spec_from_file_location("export_hindsight_uv_lock_v3", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HindsightUvLockExportV3Test(unittest.TestCase):
    def test_command_emits_sources_without_path_variant_header(self) -> None:
        command = MODULE.export_command(Path("/tool/uv"), Path("/python"), Path("/out"))
        self.assertIn("--no-header", command)
        self.assertIn("--emit-index-url", command)
        self.assertIn("--emit-find-links", command)
        self.assertIn("--offline", command)
        self.assertIn("--frozen", command)

    def test_source_prefix_and_body_are_separated_exactly(self) -> None:
        body = b"torch==2.10.0+cpu \\\n    --hash=sha256:abc\n"
        prefix = (
            b"--index-url https://pypi.org/simple\n"
            b"--extra-index-url https://download.pytorch.org/whl/cpu\n\n"
        )
        observed_prefix, directives = MODULE.split_and_validate_export(prefix + body, body)
        self.assertEqual(observed_prefix, prefix)
        self.assertEqual(len(directives), 2)

    def test_rejects_credentials_and_unexpected_sources(self) -> None:
        body = b"a==1\n"
        with self.assertRaisesRegex(RuntimeError, "credential"):
            MODULE.split_and_validate_export(
                b"--index-url https://user:secret@pypi.org/simple\n"
                b"--extra-index-url https://download.pytorch.org/whl/cpu\n" + body,
                body,
            )
        with self.assertRaisesRegex(RuntimeError, "unexpected public index"):
            MODULE.split_and_validate_export(
                b"--index-url https://pypi.org/simple\n"
                b"--extra-index-url https://example.com/simple\n" + body,
                body,
            )

    def test_body_identity_is_frozen(self) -> None:
        self.assertEqual(MODULE.BODY_BYTES, 256_006)
        self.assertEqual(
            MODULE.BODY_SHA256,
            "6f0836431e1a0ba74bdc92732ffb0a81a1c72691bdab2bc3fba43c4a1e3716c6",
        )
        self.assertEqual(MODULE.REQUIREMENT_HEAD_COUNT, 208)


if __name__ == "__main__":
    unittest.main()
