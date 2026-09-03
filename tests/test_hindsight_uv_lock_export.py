from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_hindsight_uv_lock.py"
SPEC = importlib.util.spec_from_file_location("export_hindsight_uv_lock", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HindsightUvLockExportTest(unittest.TestCase):
    def test_lock_tool_and_interpreter_identities_are_frozen(self) -> None:
        self.assertEqual(len(MODULE.SOURCE_REVISION), 40)
        self.assertEqual(MODULE.LOCK_BYTES, 1_037_159)
        self.assertEqual(len(MODULE.LOCK_SHA256), 64)
        self.assertEqual(len(MODULE.UV_SHA256), 64)
        self.assertEqual(len(MODULE.PYTHON_SHA256), 64)

    def test_export_command_is_frozen_offline_and_excludes_workspace(self) -> None:
        command = MODULE.export_command(
            Path("/project/AgentEnhance/tools/uv"),
            Path("/python3.11"),
            Path("/output.txt"),
        )
        for flag in (
            "--frozen",
            "--offline",
            "--no-cache",
            "--no-dev",
            "--no-emit-workspace",
            "--no-python-downloads",
        ):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index("--package") + 1], "hindsight-all")

    def test_requirement_head_parser_ignores_hash_continuations(self) -> None:
        text = (
            "# generated\n"
            "aiohttp==1.0 \\\n"
            "    --hash=sha256:abc\n"
            "--index-url https://example.test\n"
            "torch==2.0\n"
        )
        self.assertEqual(
            MODULE.requirement_heads(text),
            ["aiohttp==1.0 " + chr(92), "torch==2.0"],
        )


if __name__ == "__main__":
    unittest.main()
