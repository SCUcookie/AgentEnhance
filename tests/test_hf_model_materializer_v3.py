from __future__ import annotations

import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_hf_model_snapshot_v3.py"
SPEC = importlib.util.spec_from_file_location("materialize_hf_model_snapshot_v3", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def model_row() -> dict:
    return {
        "repository": "owner/model",
        "revision": "a" * 40,
        "allow_patterns": ["*"],
        "expected_files": [
            {"path": "1_Pooling/config.json", "bytes": 3},
            {
                "path": "model.safetensors",
                "bytes": 3,
                "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            },
        ],
        "expected_file_count": 2,
        "expected_total_bytes": 6,
    }


class HfModelMaterializerV3Test(unittest.TestCase):
    def test_select_model_accepts_safe_nested_files_and_wildcard_manifest(self) -> None:
        row = model_row()
        self.assertIs(
            MODULE.select_model(
                {"status": "FROZEN_BEFORE_DOWNLOAD", "models": [row]}, "owner/model"
            ),
            row,
        )

    def test_select_model_rejects_parent_and_unsorted_paths(self) -> None:
        row = model_row()
        row["expected_files"][0]["path"] = "../config.json"
        with self.assertRaisesRegex(ValueError, "unsafe"):
            MODULE.select_model(
                {"status": "FROZEN_BEFORE_DOWNLOAD", "models": [row]}, "owner/model"
            )
        row = model_row()
        row["expected_files"].reverse()
        with self.assertRaisesRegex(ValueError, "unique and sorted"):
            MODULE.select_model(
                {"status": "FROZEN_BEFORE_DOWNLOAD", "models": [row]}, "owner/model"
            )

    def test_file_url_preserves_valid_nested_segments(self) -> None:
        self.assertEqual(
            MODULE.file_url("owner/model", "a" * 40, "1 Pooling/config.json"),
            "https://huggingface.co/owner/model/resolve/"
            + "a" * 40
            + "/1%20Pooling/config.json?download=true",
        )

    def test_stream_exact_file_hashes_and_caps_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "file.partial"
            self.assertEqual(
                MODULE.stream_exact_file(io.BytesIO(b"abc"), destination, 3),
                (3, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
            )
            with self.assertRaisesRegex(RuntimeError, "exceeded frozen byte size"):
                MODULE.stream_exact_file(
                    io.BytesIO(b"abcd"), Path(directory) / "large.partial", 3
                )

    def test_observed_files_is_recursive_and_excludes_partials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "1_Pooling").mkdir()
            (root / "1_Pooling/config.json").write_bytes(b"abc")
            (root / "model.partial").write_bytes(b"abc")
            self.assertEqual(MODULE.observed_files(root), ["1_Pooling/config.json"])

    def test_resolves_environment_backed_contract_path(self) -> None:
        with patch.dict(os.environ, {"AGENT_ENHANCE_REMOTE_ROOT": "/volume/AgentEnhance"}):
            self.assertEqual(
                MODULE.resolve_manifest_path(
                    "${AGENT_ENHANCE_REMOTE_ROOT}/cache/models/example"
                ),
                Path("/volume/AgentEnhance/cache/models/example"),
            )


if __name__ == "__main__":
    unittest.main()
