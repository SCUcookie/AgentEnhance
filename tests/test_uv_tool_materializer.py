from __future__ import annotations

import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_uv_tool.py"
SPEC = importlib.util.spec_from_file_location("materialize_uv_tool", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UvToolMaterializerTest(unittest.TestCase):
    def test_release_identity_is_frozen(self) -> None:
        self.assertEqual(MODULE.VERSION, "0.12.9")
        self.assertEqual(MODULE.TARGET_TRIPLE, "x86_64-unknown-linux-gnu")
        self.assertEqual(MODULE.ARCHIVE_BYTES, 19_423_276)
        self.assertEqual(len(MODULE.ARCHIVE_SHA256), 64)

    def test_archive_validator_rejects_extra_member(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.tar.gz"
            with tarfile.open(path, "w:gz") as archive:
                for name in [
                    f"uv-{MODULE.TARGET_TRIPLE}",
                    f"uv-{MODULE.TARGET_TRIPLE}/uv",
                    f"uv-{MODULE.TARGET_TRIPLE}/uvx",
                    f"uv-{MODULE.TARGET_TRIPLE}/unexpected",
                ]:
                    info = tarfile.TarInfo(name)
                    if name.endswith(MODULE.TARGET_TRIPLE):
                        info.type = tarfile.DIRTYPE
                        archive.addfile(info)
                    else:
                        payload = b"binary"
                        info.size = len(payload)
                        archive.addfile(info, io.BytesIO(payload))
            with tarfile.open(path, "r:gz") as archive:
                with self.assertRaisesRegex(RuntimeError, "unexpected archive members"):
                    MODULE.validate_archive_members(archive)


if __name__ == "__main__":
    unittest.main()
