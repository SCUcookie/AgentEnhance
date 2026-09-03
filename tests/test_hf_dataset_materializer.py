from __future__ import annotations

import hashlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_hf_dataset_snapshot.py"
SPEC = importlib.util.spec_from_file_location("materialize_hf_dataset_snapshot", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def sample_manifest() -> dict:
    return {
        "status": "FROZEN_BEFORE_DOWNLOAD",
        "source": {"repository": "owner/dataset", "revision": "a" * 40},
        "expected": {"files": 2, "bytes": 6},
        "files": [
            {"path": "README.md", "bytes": 3, "git_oid": git_blob_sha1(b"abc")},
            {
                "path": "data/image/a.jpg",
                "bytes": 3,
                "git_oid": "b" * 40,
                "lfs_sha256": hashlib.sha256(b"xyz").hexdigest(),
            },
        ],
    }


class HfDatasetMaterializerTest(unittest.TestCase):
    def test_manifest_requires_sorted_safe_exact_identities(self) -> None:
        payload = sample_manifest()
        self.assertEqual(MODULE.validate_manifest(payload), payload["files"])
        payload["files"][0]["path"] = "../README.md"
        with self.assertRaisesRegex(ValueError, "unsafe"):
            MODULE.validate_manifest(payload)

    def test_stream_computes_sha256_and_git_blob(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observed = MODULE.stream_exact_file(
                io.BytesIO(b"abc"), Path(directory) / "file.partial", 3
            )
        self.assertEqual(observed[0], 3)
        self.assertEqual(observed[1], hashlib.sha256(b"abc").hexdigest())
        self.assertEqual(observed[2], git_blob_sha1(b"abc"))

    def test_dataset_url_binds_revision_and_escapes_path(self) -> None:
        url = MODULE.dataset_file_url("owner/data set", "a" * 40, "data/a b.json")
        self.assertEqual(
            url,
            "https://huggingface.co/datasets/owner/data%20set/resolve/"
            + "a" * 40
            + "/data/a%20b.json?download=true",
        )

    def test_exact_child_scope_rejects_nested_or_unrelated_paths(self) -> None:
        scope = Path("/data1/2026/ldh/AgentEnhance/datasets/raw")
        MODULE.validate_exact_child(scope / "dataset", (scope,), "target")
        with self.assertRaisesRegex(ValueError, "exact child"):
            MODULE.validate_exact_child(scope / "nested" / "dataset", (scope,), "target")
        with self.assertRaisesRegex(ValueError, "exact child"):
            MODULE.validate_exact_child(Path("/tmp/dataset"), (scope,), "target")

    def test_marker_must_remain_under_project_run_scope(self) -> None:
        scope = Path("/data1/2026/ldh/AgentEnhance/runs")
        MODULE.validate_under_scope(scope / "controller" / "TERMINAL_ACCEPTED", (scope,), "marker")
        with self.assertRaisesRegex(ValueError, "outside allowed scopes"):
            MODULE.validate_under_scope(Path("/tmp/TERMINAL_ACCEPTED"), (scope,), "marker")


if __name__ == "__main__":
    unittest.main()
