from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import audit_memgallery_dataset as dataset_audit  # noqa: E402
import memgallery_dataset_projection_loader as loader  # noqa: E402
import memgallery_lifecycle_controller as lifecycle  # noqa: E402


def canonical(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()


class MemGalleryDatasetProjectionLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.dataset = self.root / "dataset"
        self.evidence = self.root / "evidence"
        self.dataset.mkdir()
        self.evidence.mkdir()
        self.manifest_path = self.root / "manifest.json"
        self._build_fixture()
        stable = self.identity["stable_identity"]
        self.patchers = (
            mock.patch.object(lifecycle, "EXPECTED_FILES", stable["files"]),
            mock.patch.object(lifecycle, "EXPECTED_BYTES", stable["bytes"]),
            mock.patch.object(lifecycle, "EXPECTED_IMAGE_FILES", stable["image_files"]),
        )
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _build_fixture(self) -> None:
        counts = [86] * 19 + [77]
        payloads: dict[str, bytes] = {"data/image/shared.jpg": b"frozen-image"}
        for index, count in enumerate(counts):
            scenario = f"scenario-{index:02d}"
            dialogue = {
                "character_profile": {"name": "Ada"},
                "multi_session_dialogues": [{
                    "session_id": f"session-{index}",
                    "date": "2026-01-01",
                    "dialogues": [{
                        "round": "1",
                        "user": f"memory {index}",
                        "assistant": "ack",
                        **({
                            "input_image": ["../image/shared.jpg"],
                            "image_caption": ["a shared image"],
                            "image_id": ["shared"],
                        } if index == 0 else {}),
                    }],
                }],
                "human-annotated QAs": [
                    {
                        "question": f"question {scenario} {qa_index}",
                        "answer": f"secret answer {scenario} {qa_index}",
                        "point": "AR",
                        "session_id": f"session-{index}",
                        **({
                            "question_image": "../image/shared.jpg",
                            "image_caption": "a shared image",
                        } if index == 0 and qa_index == 0 else {}),
                    }
                    for qa_index in range(count)
                ],
            }
            payloads[f"data/dialog/{scenario}.json"] = json.dumps(
                dialogue, ensure_ascii=False, sort_keys=True
            ).encode() + b"\n"
        rows = []
        for relative, payload in sorted(payloads.items()):
            path = self.dataset / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            row = {"path": relative, "bytes": len(payload), "git_oid": git_blob(payload)}
            if relative.endswith(".jpg"):
                row["lfs_sha256"] = hashlib.sha256(payload).hexdigest()
            rows.append(row)
        self.manifest = {
            "status": "FROZEN_BEFORE_DOWNLOAD",
            "source": {"repository": loader.EXPECTED_REPOSITORY, "revision": loader.EXPECTED_REVISION},
            "expected": {"files": len(rows), "bytes": sum(row["bytes"] for row in rows)},
            "files": rows,
        }
        self.manifest_path.write_text(json.dumps(self.manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        audited = dataset_audit.audit_dataset(self.dataset, self.manifest, loader.EXPECTED_QUESTIONS)
        question_path = self.evidence / "question-index.jsonl"
        question_path.write_bytes(audited["question_index_bytes"])
        qid_path = self.evidence / "QID_ORDER.txt"
        qid_path.write_bytes(audited["qid_bytes"])
        references_path = self.evidence / "image-references.json"
        references_path.write_text(json.dumps({
            "references": audited["image_references"],
            "referenced_images": audited["referenced_images"],
            "unreferenced_images": audited["unreferenced_images"],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.identity = {
            "schema_version": "agentenhance.memgallery_dataset_integrity.v1",
            "status": "TERMINAL_ACCEPTED",
            "dataset_root": str(self.dataset),
            "source_manifest": str(self.manifest_path),
            "source_manifest_sha256": sha(self.manifest_path),
            "stable_identity": audited["stable_identity"],
            "dataset_semantic_identity_sha256": audited["dataset_semantic_identity_sha256"],
            "scenarios": audited["scenarios"],
        }
        identity_path = self.evidence / "dataset-integrity.json"
        identity_path.write_text(json.dumps(self.identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._resign_evidence()
        (self.evidence / "TERMINAL_ACCEPTED").touch()

    def _resign_evidence(self) -> None:
        signed = [
            self.evidence / "dataset-integrity.json",
            self.evidence / "question-index.jsonl",
            self.evidence / "QID_ORDER.txt",
            self.evidence / "image-references.json",
        ]
        (self.evidence / "EVIDENCE_SHA256SUMS").write_text(
            "".join(f"{sha(path)}  {path}\n" for path in signed), encoding="utf-8"
        )

    def load(self) -> dict:
        return loader.load_accepted_projections(
            dataset_root=self.dataset,
            evidence_root=self.evidence,
            source_manifest_path=self.manifest_path,
            expected_scenarios=20,
            expected_questions=1711,
            expected_image_files=1,
        )

    def test_full_projection_is_ordered_answer_free_and_image_bound(self) -> None:
        result = self.load()
        self.assertEqual(result["status"], "ACCEPTED_ANSWER_FREE_PROJECTION")
        self.assertEqual(result["scenario_count"], 20)
        self.assertEqual(result["question_count"], 1711)
        self.assertEqual(result["memory_record_count"], 20)
        self.assertEqual(result["image_count"], 1)
        self.assertEqual(result["raw_answers_returned"], 0)
        serialized = json.dumps(result["scenarios"], ensure_ascii=False)
        self.assertNotIn("secret answer", serialized)

    def test_dialog_drift_after_integrity_audit_is_rejected(self) -> None:
        path = self.dataset / "data/dialog/scenario-00.json"
        path.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "manifest byte drift"):
            self.load()

    def test_source_manifest_byte_drift_is_rejected(self) -> None:
        self.manifest_path.write_text(json.dumps(self.manifest) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source manifest byte identity drift"):
            self.load()

    def test_reordered_scenarios_cannot_be_resigned_into_acceptance(self) -> None:
        identity_path = self.evidence / "dataset-integrity.json"
        payload = json.loads(identity_path.read_text())
        payload["scenarios"].reverse()
        identity_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._resign_evidence()
        with self.assertRaisesRegex(ValueError, "query projection identity drift"):
            self.load()

    def test_image_partition_drift_is_rejected(self) -> None:
        path = self.evidence / "image-references.json"
        payload = json.loads(path.read_text())
        payload["referenced_images"] = []
        payload["unreferenced_images"] = ["data/image/shared.jpg"]
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._resign_evidence()
        with self.assertRaisesRegex(ValueError, "image references differ from partition"):
            self.load()

    def test_image_byte_drift_after_integrity_audit_is_rejected(self) -> None:
        path = self.dataset / "data/image/shared.jpg"
        path.write_bytes(b"frozen-imagf")
        with self.assertRaisesRegex(ValueError, "manifest LFS digest drift"):
            self.load()


if __name__ == "__main__":
    unittest.main()
