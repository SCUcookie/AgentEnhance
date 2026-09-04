from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "memgallery_answer_contract.py"
SPEC = importlib.util.spec_from_file_location("memgallery_answer_contract", MODULE_PATH)
assert SPEC and SPEC.loader
answer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(answer)


def query(**overrides: object) -> dict:
    base = {
        "qid": "ava:0",
        "question": "What color was the bicycle?",
        "speaker_a": "user (Ava)",
        "speaker_b": "assistant",
        "category": "VS",
        "question_image_id": None,
    }
    base.update(overrides)
    return base


class MemGalleryAnswerContractTests(unittest.TestCase):
    def test_text_request_freezes_model_decoding_and_category_constraint(self) -> None:
        request = answer.build_answer_request(
            [{"text": "user (Ava): The bicycle was red."}],
            query(),
            multimodal_memory=False,
            seed=1,
        )
        self.assertEqual(request["model"], "Qwen3-VL-8B-Instruct")
        self.assertEqual(request["temperature"], 0.0)
        self.assertEqual(request["max_tokens"], 128)
        self.assertEqual(request["seed"], 1)
        self.assertIn("Return the image_id", request["messages"][1]["content"][-1]["text"])

    def test_multimodal_evidence_preserves_image_order_and_source_id(self) -> None:
        request = answer.build_answer_request(
            [
                {
                    "multimodal_text": "user: first",
                    "image_ids": ["data/image/first.jpg"],
                    "source_image_id": "IMG_1",
                },
                {"multimodal_text": "assistant: second", "image_ids": [], "source_image_id": None},
            ],
            query(question_image_id="data/image/query.jpg"),
            multimodal_memory=True,
            seed=0,
        )
        content = request["messages"][1]["content"]
        self.assertEqual([item["type"] for item in content], ["text", "text", "image_ref", "text", "text", "text", "image_ref"])
        self.assertIn("image_id: IMG_1", content[1]["text"])
        self.assertEqual(content[2]["image_id"], "data/image/first.jpg")
        self.assertEqual(content[-1]["image_id"], "data/image/query.jpg")

    def test_no_memory_still_has_header_and_question(self) -> None:
        request = answer.build_answer_request([], query(category=""), multimodal_memory=False, seed=2)
        content = request["messages"][1]["content"]
        self.assertEqual(content[0], {"type": "text", "text": answer.MEMORY_HEADER})
        self.assertIn("The current question", content[1]["text"])

    def test_raw_answer_fields_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "leaked"):
            answer.build_answer_request([], query(answer="Red."), multimodal_memory=False, seed=0)

    def test_multiple_images_per_round_are_rejected(self) -> None:
        evidence = [{"multimodal_text": "user: x", "image_ids": ["a.jpg", "b.jpg"]}]
        with self.assertRaisesRegex(ValueError, "at most one"):
            answer.build_answer_request(evidence, query(), multimodal_memory=True, seed=0)


if __name__ == "__main__":
    unittest.main()
