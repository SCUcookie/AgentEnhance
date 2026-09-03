from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "materialize_uv_tool_from_staged_assets_v2.py"
SPEC = importlib.util.spec_from_file_location("materialize_uv_tool_from_staged_assets_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UvToolStagedMaterializerV2Test(unittest.TestCase):
    def test_only_version_output_contract_changes(self) -> None:
        self.assertEqual(MODULE.base.VERSION, "0.12.9")
        self.assertEqual(MODULE.base.TARGET_TRIPLE, "x86_64-unknown-linux-gnu")
        self.assertEqual(
            MODULE.EXPECTED_VERSION_OUTPUT,
            "uv 0.12.9 (x86_64-unknown-linux-gnu)",
        )
        self.assertEqual(MODULE.base.ARCHIVE_BYTES, 19_423_276)


if __name__ == "__main__":
    unittest.main()
