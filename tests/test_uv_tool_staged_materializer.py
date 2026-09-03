from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "materialize_uv_tool_from_staged_assets.py"
SPEC = importlib.util.spec_from_file_location("materialize_uv_tool_from_staged_assets", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UvToolStagedMaterializerTest(unittest.TestCase):
    def test_recovery_preserves_original_release_identity(self) -> None:
        self.assertEqual(MODULE.base.VERSION, "0.12.9")
        self.assertEqual(MODULE.base.ARCHIVE_BYTES, 19_423_276)
        self.assertEqual(
            MODULE.base.ARCHIVE_SHA256,
            "ec7a99cd05e0cd7f80243f135ce1361c76835cb0ee60055d14d20eba8eba1460",
        )
        self.assertEqual(MODULE.base.CHECKSUM_BYTES, 101)


if __name__ == "__main__":
    unittest.main()
