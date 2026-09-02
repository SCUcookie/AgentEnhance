import json
import tempfile
import unittest
from pathlib import Path

from agent_enhance.hashing import FingerprintError, fingerprint
from agent_enhance.validation import validate_project


ROOT = Path(__file__).resolve().parents[1]


class FingerprintTests(unittest.TestCase):
    def test_file_fingerprint_is_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txt"
            path.write_bytes(b"agent-enhance\n")
            self.assertEqual(fingerprint(path), fingerprint(path))
            self.assertEqual(fingerprint(path)["size"], 14)

    def test_directory_fingerprint_changes_with_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.txt").write_text("one", encoding="utf-8")
            first = fingerprint(root)["sha256"]
            (root / "sample.txt").write_text("two", encoding="utf-8")
            second = fingerprint(root)["sha256"]
            self.assertNotEqual(first, second)

    def test_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.txt"
            target.write_text("content", encoding="utf-8")
            link = root / "link.txt"
            link.symlink_to(target)
            with self.assertRaises(FingerprintError):
                fingerprint(root)


class RepositoryValidationTests(unittest.TestCase):
    def test_repository_contracts_pass(self):
        self.assertEqual(validate_project(ROOT), [])

    def test_all_json_files_parse(self):
        for path in ROOT.rglob("*.json"):
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
