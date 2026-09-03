from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_memgallery_dataset.py"
SPEC = importlib.util.spec_from_file_location("audit_memgallery_dataset", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def write_fixture(root: Path, missing_reference: bool = False) -> dict:
    image = b"image"
    dialog = {
        "character_profile": {"name": "Ada"},
        "multi_session_dialogues": [
            {
                "session_id": "s1",
                "date": "2026-01-01",
                "dialogues": [
                    {
                        "round": "r1",
                        "user": "hello",
                        "assistant": "hi",
                        "input_image": [
                            "../image/scenario/missing.jpg"
                            if missing_reference
                            else "../image/scenario/a.jpg"
                        ],
                        "image_caption": ["caption"],
                        "image_id": ["i1"],
                    }
                ],
            }
        ],
        "human-annotated QAs": [
            {"question": "What?", "answer": "This.", "point": "AR", "clue": ["r1"]},
            {
                "question": "Which image?",
                "answer": "A.",
                "question_image": "../image/scenario/a.jpg",
                "image_caption": "caption",
            },
        ],
    }
    dialog_bytes = (json.dumps(dialog, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    readme = b"fixture\n"
    payloads = {
        "README.md": readme,
        "data/dialog/scenario.json": dialog_bytes,
        "data/image/scenario/a.jpg": image,
    }
    for relative, data in payloads.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    files = []
    for relative, data in sorted(payloads.items()):
        row = {"path": relative, "bytes": len(data), "git_oid": git_blob_sha1(data)}
        if relative.endswith(".jpg"):
            row["lfs_sha256"] = hashlib.sha256(data).hexdigest()
        files.append(row)
    return {
        "status": "FROZEN_BEFORE_DOWNLOAD",
        "source": {"repository": "Ethan-Bei/Mem-Gallery", "revision": "a" * 40},
        "expected": {"files": len(files), "bytes": sum(len(data) for data in payloads.values())},
        "files": files,
    }


class MemGalleryDatasetAuditTest(unittest.TestCase):
    def test_audit_freezes_runner_order_and_semantic_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = write_fixture(root)
            first = MODULE.audit_dataset(root, manifest, expected_questions=2)
            second = MODULE.audit_dataset(root, manifest, expected_questions=2)
        self.assertEqual([row["qid"] for row in first["question_rows"]], ["scenario:0", "scenario:1"])
        self.assertEqual(first["stable_identity"]["questions"], 2)
        self.assertEqual(first["stable_identity"]["dialogue_rounds"], 1)
        self.assertEqual(first["dataset_semantic_identity_sha256"], second["dataset_semantic_identity_sha256"])

    def test_missing_frozen_image_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = write_fixture(root, missing_reference=True)
            with self.assertRaisesRegex(ValueError, "absent from the frozen manifest"):
                MODULE.audit_dataset(root, manifest, expected_questions=2)

    def test_question_denominator_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = write_fixture(root)
            with self.assertRaisesRegex(ValueError, "question denominator mismatch"):
                MODULE.audit_dataset(root, manifest, expected_questions=3)

    def test_image_reference_safety(self) -> None:
        self.assertEqual(
            MODULE.resolve_image_reference("../image/scenario/a.jpg", "question"),
            "data/image/scenario/a.jpg",
        )
        with self.assertRaisesRegex(ValueError, "absolute"):
            MODULE.resolve_image_reference("/tmp/a.jpg", "question")
        with self.assertRaisesRegex(ValueError, "unsafe"):
            MODULE.resolve_image_reference("../image/../secret.jpg", "conversation")


if __name__ == "__main__":
    unittest.main()
