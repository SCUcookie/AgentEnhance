from __future__ import annotations

import argparse
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fetch_hf_dataset_tree_manifest",
    ROOT / "scripts" / "fetch_hf_dataset_tree_manifest.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HfDatasetTreeManifestTest(unittest.TestCase):
    def test_normalize_sorts_and_keeps_lfs_identity(self) -> None:
        entries = [
            {
                "type": "file",
                "path": "data/image/z.jpg",
                "size": 7,
                "oid": "b" * 40,
                "lfs": {"oid": "c" * 64, "size": 7, "pointerSize": 126},
                "xetHash": "d" * 64,
            },
            {"type": "directory", "path": "data", "size": 0, "oid": "e" * 40},
            {"type": "file", "path": "README.md", "size": 3, "oid": "a" * 40},
        ]
        files = MODULE.normalize_files(entries)
        self.assertEqual([item["path"] for item in files], ["README.md", "data/image/z.jpg"])
        self.assertEqual(files[1]["lfs_sha256"], "c" * 64)
        self.assertEqual(files[1]["bytes"], 7)

    def test_normalize_rejects_parent_path(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unsafe"):
            MODULE.normalize_files(
                [{"type": "file", "path": "../escape", "size": 1, "oid": "a" * 40}]
            )

    def test_build_manifest_recomputes_cardinality(self) -> None:
        files = MODULE.normalize_files(
            [
                {"type": "file", "path": "data/dialog/a.json", "size": 2, "oid": "a" * 40},
                {
                    "type": "file",
                    "path": "data/image/a.png",
                    "size": 5,
                    "oid": "b" * 40,
                    "lfs": {"oid": "c" * 64, "size": 5, "pointerSize": 126},
                },
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            args = argparse.Namespace(
                repo_id="owner/dataset",
                revision="f" * 40,
                manifest_id="unit",
                observed_at="2026-09-04T00:00:00+08:00",
                license="mit",
                output=Path(temp_dir) / "manifest.json",
            )
            manifest = MODULE.build_manifest(args, files)
        self.assertEqual(manifest["expected"]["files"], 2)
        self.assertEqual(manifest["expected"]["bytes"], 7)
        self.assertEqual(manifest["expected"]["dialog_files"], 1)
        self.assertEqual(manifest["expected"]["image_files"], 1)


if __name__ == "__main__":
    unittest.main()
