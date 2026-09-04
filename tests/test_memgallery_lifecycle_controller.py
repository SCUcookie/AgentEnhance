from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "memgallery_lifecycle_controller.py"
SPEC = importlib.util.spec_from_file_location("memgallery_lifecycle_controller", MODULE_PATH)
assert SPEC and SPEC.loader
controller = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(controller)


def canonical(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def accepted_answer(request):
    return "synthetic answer", {
        "schema_version": "agentenhance.memgallery_endpoint_call.v1",
        "call_category": "final_answer",
        "status": "ACCEPTED",
        "attempts": 1,
        "retry_count": 0,
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_tokens": 2,
        "wall_seconds": 0.0,
    }


def build_dataset_evidence(root: Path) -> tuple[list[dict], list[dict]]:
    scenario_counts = [86] * 19 + [77]
    question_rows = []
    projections = []
    scenarios = []
    for scenario_index, count in enumerate(scenario_counts):
        scenario = f"scenario-{scenario_index:02d}"
        queries = []
        for qa_index in range(count):
            qid = f"{scenario}:{qa_index}"
            row = {
                "qid": qid,
                "scenario": scenario,
                "qa_index": qa_index,
                "question_sha256": hashlib.sha256(f"q-{qid}".encode()).hexdigest(),
                "answer_sha256": hashlib.sha256(f"a-{qid}".encode()).hexdigest(),
                "qa_canonical_sha256": hashlib.sha256(f"qa-{qid}".encode()).hexdigest(),
            }
            question_rows.append(row)
            queries.append({**row, "question": "What?", "retrieval_query_text": "What?", "speaker_a": "user", "speaker_b": "assistant", "category": "", "question_image_id": None})
        projections.append({
            "scenario": scenario,
            "memory_records": [{"memory_id": f"{scenario}:session-0:round-0", "chronological_index": 0, "text": "user: fixture", "multimodal_text": "user: fixture", "image_ids": [], "source_image_id": None}],
            "queries": queries,
        })
        scenarios.append({"scenario": scenario, "questions": count})

    question_path = root / "question-index.jsonl"
    question_path.write_bytes(b"".join(canonical(row) for row in question_rows))
    qid_path = root / "QID_ORDER.txt"
    qid_path.write_text("".join(f"{row['qid']}\n" for row in question_rows), encoding="utf-8")
    image_path = root / "image-references.json"
    image_path.write_text("{}\n", encoding="utf-8")
    stable = {
        "repository": controller.EXPECTED_REPOSITORY,
        "revision": controller.EXPECTED_REVISION,
        "manifest_sha256": "a" * 64,
        "files": controller.EXPECTED_FILES,
        "bytes": controller.EXPECTED_BYTES,
        "dialog_files": controller.EXPECTED_SCENARIOS,
        "image_files": controller.EXPECTED_IMAGE_FILES,
        "sessions": 20,
        "dialogue_rounds": 20,
        "runner_consumed_dialogue_rounds": 20,
        "questions": controller.EXPECTED_QUESTIONS,
        "qid_order_sha256": sha(qid_path),
        "question_index_sha256": sha(question_path),
        "referenced_images": 0,
        "unreferenced_images": controller.EXPECTED_IMAGE_FILES,
    }
    identity = {
        "schema_version": "agentenhance.memgallery_dataset_integrity.v1",
        "status": "TERMINAL_ACCEPTED",
        "stable_identity": stable,
        "dataset_semantic_identity_sha256": hashlib.sha256(canonical(stable)).hexdigest(),
        "scenarios": scenarios,
    }
    identity_path = root / "dataset-integrity.json"
    identity_path.write_text(json.dumps(identity, sort_keys=True) + "\n", encoding="utf-8")
    signed = [identity_path, question_path, qid_path, image_path]
    (root / "EVIDENCE_SHA256SUMS").write_text("".join(f"{sha(path)}  {path}\n" for path in signed), encoding="utf-8")
    (root / "TERMINAL_ACCEPTED").touch()
    return projections, question_rows


def model_receipts() -> dict:
    return {
        model_id: {
            "status": "TERMINAL_ACCEPTED",
            "repository": repository,
            "revision": revision,
            "inventory_sha256": hashlib.sha256(model_id.encode()).hexdigest(),
            "files": 1,
            "bytes": 1,
            "offline_load_passed": True,
            "network_requests": 0,
            "symlinks": 0,
        }
        for model_id, (repository, revision) in controller.REQUIRED_MODELS.items()
    }


def release_receipt(active: bool = False) -> dict:
    return {
        "status": "RUNNING" if active else "TERMINAL_ACCEPTED",
        "terminal_rejected": False,
        "project_process_count": 1 if active else 0,
        "project_tmux_count": 1 if active else 0,
        "model_service_count": 1 if active else 0,
        "closure_audit_sha256": "b" * 64,
    }


def authorization(mode: str = "synthetic") -> dict:
    return {
        "status": "AUTHORIZED_SYNTHETIC_LIFECYCLE",
        "mode": mode,
        "real_model_calls": False,
        "scoring": False,
        "official_values_used": False,
        "resource_ceilings": {"network_requests": 0, "gpu_processes": 0, "wall_seconds": 300, "disk_bytes": 268435456},
    }


def service(receipts: dict) -> dict:
    return {
        "status": "TERMINAL_ACCEPTED_SYNTHETIC_INERT",
        "mode": "injected_mock",
        "served_model": "Qwen3-VL-8B-Instruct",
        "model_inventory_sha256": receipts["shared-qwen3-vl-8b-answer"]["inventory_sha256"],
        "tokenizer_repository": controller.REQUIRED_MODELS["shared-qwen3-vl-8b-answer"][0],
        "tokenizer_revision": controller.REQUIRED_MODELS["shared-qwen3-vl-8b-answer"][1],
        "network_requests": 0,
        "gpu_processes_started": 0,
        "endpoint_requests": 0,
    }


class MemGalleryLifecycleControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.scope = Path(self.temporary.name).resolve()
        self.evidence = self.scope / "evidence"
        self.evidence.mkdir()
        self.projections, self.questions = build_dataset_evidence(self.evidence)
        self.models = model_receipts()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def execute_lifecycle(self, *, output_name="run", release=None, auth=None):
        return controller.run_synthetic_lifecycle(
            self.scope / output_name,
            allowed_run_scopes=[self.scope],
            method_id="no-memory",
            seed=0,
            scenario_projections=self.projections,
            dataset_evidence_root=self.evidence,
            wave1_release_receipt=release or release_receipt(),
            model_receipts=self.models,
            service_receipt=service(self.models),
            authorization=auth or authorization(),
            method_source={"identity_frozen": True, "implementation_sha256": "c" * 64},
            memory_budget={"prospectively_frozen": True, "top_k": 0},
            token_count=lambda text: len(text.split()),
            answer_call=accepted_answer,
        )

    def test_active_wave1_denies_before_run_root_creation(self) -> None:
        with self.assertRaisesRegex(ValueError, "not terminal-accepted"):
            self.execute_lifecycle(release=release_receipt(active=True))
        self.assertFalse((self.scope / "run").exists())

    def test_missing_dataset_marker_or_hash_drift_denies_before_root(self) -> None:
        (self.evidence / "TERMINAL_ACCEPTED").unlink()
        with self.assertRaisesRegex(ValueError, "acceptance marker"):
            self.execute_lifecycle()
        self.assertFalse((self.scope / "run").exists())
        (self.evidence / "TERMINAL_ACCEPTED").touch()
        (self.evidence / "QID_ORDER.txt").write_text("drift\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash drift"):
            self.execute_lifecycle(output_name="run2")
        self.assertFalse((self.scope / "run2").exists())

    def test_existing_output_root_is_rejected(self) -> None:
        (self.scope / "run").mkdir()
        with self.assertRaisesRegex(ValueError, "existing output root"):
            self.execute_lifecycle()

    def test_real_mode_is_unconditionally_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "real lifecycle mode is prohibited"):
            self.execute_lifecycle(auth=authorization(mode="real"))
        self.assertFalse((self.scope / "run").exists())

    def test_model_or_service_identity_drift_is_rejected(self) -> None:
        self.models["shared-qwen3-vl-8b-answer"]["revision"] = "d" * 40
        with self.assertRaisesRegex(ValueError, "model revision drift"):
            self.execute_lifecycle()
        self.assertFalse((self.scope / "run").exists())

    def test_complete_synthetic_surface_is_reconciliation_compatible(self) -> None:
        identity = self.execute_lifecycle()
        self.assertEqual(identity["status"], "TERMINAL_RAW_COMPLETE")
        summary = json.loads((self.scope / "run" / "raw-run-summary.json").read_text())
        self.assertEqual(summary["prediction_rows"], controller.EXPECTED_QUESTIONS)
        self.assertEqual(summary["scores_observed"], 0)

        import reconcile_memgallery_method_run as reconcile

        dataset = json.loads((self.evidence / "dataset-integrity.json").read_text())
        predictions = reconcile.read_jsonl(self.scope / "run" / "raw-predictions.jsonl")
        result, rows = reconcile.reconcile(
            dataset,
            self.questions,
            (self.evidence / "QID_ORDER.txt").read_bytes(),
            identity,
            predictions,
        )
        self.assertEqual(result["status"], "TERMINAL_ACCEPTED")
        self.assertEqual(result["prediction_rows"], controller.EXPECTED_QUESTIONS)
        self.assertEqual(len(rows.splitlines()), controller.EXPECTED_QUESTIONS)


if __name__ == "__main__":
    unittest.main()
