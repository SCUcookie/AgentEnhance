from __future__ import annotations

import hashlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/materialize_hf_model_snapshot_v4.py"
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("materialize_hf_model_snapshot_v4", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def model_row() -> dict:
    return {
        "repository": "owner/model",
        "revision": "a" * 40,
        "expected_files": [
            {"path": "1_Pooling/config.json", "bytes": 3, "git_blob_sha1": git_blob_sha1(b"abc")},
            {
                "path": "model.safetensors",
                "bytes": 3,
                "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            },
        ],
        "expected_file_count": 2,
        "expected_total_bytes": 6,
    }


class HfModelMaterializerV4Test(unittest.TestCase):
    def test_select_model_requires_one_frozen_identity_per_file(self) -> None:
        row = model_row()
        self.assertIs(
            MODULE.select_model({"status": "FROZEN_BEFORE_DOWNLOAD", "models": [row]}, "owner/model"),
            row,
        )
        row["expected_files"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "exactly one frozen content identity"):
            MODULE.select_model({"status": "FROZEN_BEFORE_DOWNLOAD", "models": [row]}, "owner/model")

    def test_stream_computes_sha256_and_git_blob_sha1(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = MODULE.stream_exact_file(
                io.BytesIO(b"abc"), Path(directory) / "file.partial", 3
            )
        self.assertEqual(result[0], 3)
        self.assertEqual(
            result[1], "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )
        self.assertEqual(result[2], git_blob_sha1(b"abc"))

    def test_rejects_bad_git_blob_identity_and_unsafe_path(self) -> None:
        row = model_row()
        row["expected_files"][0]["git_blob_sha1"] = "0" * 39
        with self.assertRaisesRegex(ValueError, "invalid frozen Git blob SHA-1"):
            MODULE.select_model({"status": "FROZEN_BEFORE_DOWNLOAD", "models": [row]}, "owner/model")
        row = model_row()
        row["expected_files"][0]["path"] = "../config.json"
        with self.assertRaisesRegex(ValueError, "unsafe"):
            MODULE.select_model({"status": "FROZEN_BEFORE_DOWNLOAD", "models": [row]}, "owner/model")


if __name__ == "__main__":
    unittest.main()
