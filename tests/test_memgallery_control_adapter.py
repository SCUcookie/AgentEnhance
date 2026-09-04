from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "memgallery_control_adapter.py"
SPEC = importlib.util.spec_from_file_location("memgallery_control_adapter", MODULE_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


class MemGalleryControlAdapterTests(unittest.TestCase):
    def fixture(self) -> dict:
        return {
            "character_profile": {"name": "Ava"},
            "multi_session_dialogues": [
                {
                    "session_id": "s0",
                    "date": "2025-01-01",
                    "dialogues": [
                        {"user": "", "assistant": ""},
                        {
                            "user": "I bought a red bike.",
                            "assistant": "Nice!",
                            "input_image": ["../image/person/bike.jpg"],
                            "image_caption": ["A red bicycle."],
                            "image_id": ["bike-1"],
                            "round": "r1",
                        },
                    ],
                }
            ],
            "human-annotated QAs": [
                {
                    "question": "What color was the bike?",
                    "answer": "Red.",
                    "point": "VS",
                    "question_image": "person/question.jpg",
                    "image_caption": "The bike in question.",
                }
            ],
        }

    def test_round_projection_matches_official_speaker_and_caption_folding(self) -> None:
        projected = adapter.adapt_scenario(self.fixture(), "ava")
        self.assertEqual(len(projected["memory_records"]), 1)
        row = projected["memory_records"][0]
        self.assertEqual(row["memory_id"], "ava:session-0:round-1")
        self.assertEqual(row["chronological_index"], 0)
        self.assertEqual(
            row["text"],
            "user (Ava): I bought a red bike.\nassistant: Nice!\nimage:\nimage_id: bike-1\nimage_caption: A red bicycle.",
        )
        self.assertEqual(row["multimodal_text"], "user (Ava): I bought a red bike.\nassistant: Nice!")
        self.assertEqual(row["image_ids"], ["data/image/person/bike.jpg"])

    def test_query_projection_omits_raw_answer_and_adds_caption_only_for_retrieval(self) -> None:
        query = adapter.adapt_scenario(self.fixture(), "ava")["queries"][0]
        self.assertNotIn("answer", query)
        self.assertEqual(query["question"], "What color was the bike?")
        self.assertEqual(
            query["retrieval_query_text"],
            "What color was the bike?\nquestion's image:\nimage_caption: The bike in question.",
        )
        self.assertEqual(query["question_image_id"], "data/image/person/question.jpg")

    def test_projection_validates_against_frozen_question_identity(self) -> None:
        query = adapter.adapt_scenario(self.fixture(), "ava")["queries"][0]
        frozen = {key: query[key] for key in (
            "qid",
            "scenario",
            "qa_index",
            "question_sha256",
            "answer_sha256",
            "qa_canonical_sha256",
        )}
        adapter.validate_query_projection([query], [frozen])
        frozen["answer_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "answer_sha256"):
            adapter.validate_query_projection([query], [frozen])

    def test_conversation_image_resolution_rejects_escape(self) -> None:
        fixture = self.fixture()
        fixture["multi_session_dialogues"][0]["dialogues"][1]["input_image"] = ["../../secret.jpg"]
        with self.assertRaisesRegex(ValueError, "unsafe"):
            adapter.adapt_scenario(fixture, "ava")

    def test_non_string_image_metadata_fails_closed(self) -> None:
        fixture = self.fixture()
        fixture["multi_session_dialogues"][0]["dialogues"][1]["image_caption"] = [7]
        with self.assertRaisesRegex(ValueError, "image_caption"):
            adapter.adapt_scenario(fixture, "ava")


if __name__ == "__main__":
    unittest.main()
