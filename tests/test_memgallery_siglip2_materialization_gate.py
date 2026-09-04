from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gate_memgallery_siglip2_materialization.py"
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("gate_memgallery_siglip2_materialization", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_integrity_root(root: Path) -> Path:
    root.mkdir()
    qids = b"".join(f"scenario:{index}\n".encode() for index in range(1711))
    question_index = b"{}\n" * 1711
    image_refs = b"{}\n"
    payload = {
        "status": "TERMINAL_ACCEPTED",
        "dataset_semantic_identity_sha256": "a" * 64,
        "stable_identity": {
            **MODULE.EXPECTED_INTEGRITY,
            "qid_order_sha256": sha256(qids),
            "question_index_sha256": sha256(question_index),
        },
    }
    files = {
        "dataset-integrity.json": (json.dumps(payload, sort_keys=True) + "\n").encode(),
        "question-index.jsonl": question_index,
        "QID_ORDER.txt": qids,
        "image-references.json": image_refs,
    }
    for name, data in files.items():
        (root / name).write_bytes(data)
    (root / "EVIDENCE_SHA256SUMS").write_text(
        "".join(f"{sha256(data)}  {root / name}\n" for name, data in files.items()),
        encoding="utf-8",
    )
    (root / "TERMINAL_ACCEPTED").touch()
    return root


class MemGallerySiglip2MaterializationGateTest(unittest.TestCase):
    def test_active_wave1_process_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "process remains active"):
            MODULE.assert_resources_released(
                ["python run_wma_seeded.py --sample-index 35"], set()
            )

    def test_blocked_service_port_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "ports remain listening"):
            MODULE.assert_resources_released([], {18120})

    def test_integrity_rejects_missing_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = make_integrity_root(Path(directory) / "integrity")
            (root / "TERMINAL_ACCEPTED").unlink()
            with self.assertRaisesRegex(RuntimeError, "not terminal accepted"):
                MODULE.verify_dataset_integrity(root)

    def test_full_preflight_accepts_only_complete_released_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            wave1 = base / "wave1"
            wave1.mkdir()
            (wave1 / "TERMINAL_ACCEPTED").touch()
            integrity = make_integrity_root(base / "integrity")
            report = MODULE.preflight(
                contract_path=ROOT / "comparisons/memgallery-siglip2-model-materialization-prefreeze.v1.json",
                ledger_path=ROOT / "comparisons/baseline-model-ownership-ledger.v2.json",
                prefetch_manifest=ROOT / "comparisons/memgallery-siglip2-model-prefetch-manifest.v1.json",
                materializer=ROOT / "scripts/materialize_hf_model_snapshot_v4.py",
                remote_root=Path("/data1/2026/ldh/AgentEnhance"),
                wave1_controller_root=wave1,
                dataset_integrity_root=integrity,
                command_lines=[],
                observed_listening_ports=set(),
            )
        self.assertEqual(report["status"], "PREFLIGHT_ACCEPTED")
        self.assertEqual(report["dataset_integrity"]["signed_payloads"], 4)
        self.assertEqual(report["ownership"]["required_dependents"], ["memgallery-m2a", "memgallery-v-mem"])
        self.assertEqual(report["network_requests_started"], 0)


if __name__ == "__main__":
    unittest.main()
