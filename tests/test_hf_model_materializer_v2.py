from __future__ import annotations

import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_hf_model_snapshot_v2.py"
SPEC = importlib.util.spec_from_file_location("materialize_hf_model_snapshot_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def model_row() -> dict:
    return {
        "repository": "owner/model",
        "revision": "a" * 40,
        "allow_patterns": ["config.json"],
        "expected_files": [
            {
                "path": "config.json",
                "bytes": 3,
                "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            }
        ],
        "expected_file_count": 1,
        "expected_total_bytes": 3,
    }


class HfModelMaterializerV2Test(unittest.TestCase):
    def test_select_model_requires_exact_ordered_allowlist_and_hash(self) -> None:
        row = model_row()
        self.assertIs(
            MODULE.select_model({"status": "FROZEN_BEFORE_DOWNLOAD", "models": [row]}, "owner/model"),
            row,
        )
        row["expected_files"][0]["sha256"] = "0" * 63
        with self.assertRaisesRegex(ValueError, "invalid frozen SHA-256"):
            MODULE.select_model({"status": "FROZEN_BEFORE_DOWNLOAD", "models": [row]}, "owner/model")

    def test_select_model_rejects_nested_or_parent_paths(self) -> None:
        row = model_row()
        row["allow_patterns"] = ["../config.json"]
        row["expected_files"][0]["path"] = "../config.json"
        with self.assertRaisesRegex(ValueError, "unsafe or nested"):
            MODULE.select_model({"status": "FROZEN_BEFORE_DOWNLOAD", "models": [row]}, "owner/model")

    def test_stream_exact_file_hashes_and_caps_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "file.partial"
            self.assertEqual(
                MODULE.stream_exact_file(io.BytesIO(b"abc"), destination, 3),
                (3, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
            )
            with self.assertRaisesRegex(RuntimeError, "exceeded frozen byte size"):
                MODULE.stream_exact_file(io.BytesIO(b"abcd"), Path(directory) / "large.partial", 3)

    def test_resolves_environment_backed_contract_path(self) -> None:
        with patch.dict(os.environ, {"AGENT_ENHANCE_REMOTE_ROOT": "/volume/AgentEnhance"}):
            self.assertEqual(
                MODULE.resolve_manifest_path("${AGENT_ENHANCE_REMOTE_ROOT}/cache/models/example"),
                Path("/volume/AgentEnhance/cache/models/example"),
            )


if __name__ == "__main__":
    unittest.main()
