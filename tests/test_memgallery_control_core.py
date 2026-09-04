from __future__ import annotations

import importlib.util
import math
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "memgallery_control_core.py"
SPEC = importlib.util.spec_from_file_location("memgallery_control_core", MODULE_PATH)
assert SPEC and SPEC.loader
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


def record(memory_id: str, index: int, text: str, images: list[str] | None = None) -> dict:
    return {
        "memory_id": memory_id,
        "chronological_index": index,
        "text": text,
        "image_ids": images or [],
    }


class MemGalleryControlCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            record("r0", 0, "red apple"),
            record("r1", 1, "blue ocean"),
            record("r2", 2, "green apple tree"),
        ]

    def test_unicode_word_tokenization_is_casefolded(self) -> None:
        self.assertEqual(core.unicode_word_tokens("ÄPFEL，北京! 42"), ["äpfel", "北京", "42"])

    def test_bm25_prefers_matching_documents(self) -> None:
        ranked = core.retrieve_control("bm25", self.records, "green tree", top_k=2)
        self.assertEqual([item["memory_id"] for item in ranked], ["r2", "r0"])

    def test_score_ties_use_chronological_index(self) -> None:
        ranked = core.retrieve_control("bm25", self.records, "absent", top_k=3)
        self.assertEqual([item["memory_id"] for item in ranked], ["r0", "r1", "r2"])

    def test_no_memory_and_fifo_are_deterministic(self) -> None:
        self.assertEqual(core.retrieve_control("no-memory", self.records, "anything"), [])
        recent = core.retrieve_control("fifo-recent", self.records, "anything", top_k=2)
        self.assertEqual([item["memory_id"] for item in recent], ["r1", "r2"])

    def test_dense_ranking_uses_cosine(self) -> None:
        ranked = core.retrieve_control(
            "naive-rag",
            self.records,
            "unused",
            top_k=2,
            dense_document_vectors=[[1.0, 0.0], [0.0, 1.0], [0.8, 0.2]],
            dense_query_vector=[1.0, 0.0],
        )
        self.assertEqual([item["memory_id"] for item in ranked], ["r0", "r2"])

    def test_hybrid_rrf_combines_sparse_and_dense_ranks(self) -> None:
        ranked = core.retrieve_control(
            "hybrid-rag",
            self.records,
            "green apple",
            top_k=3,
            dense_document_vectors=[[0.0, 1.0], [1.0, 0.0], [0.8, 0.2]],
            dense_query_vector=[1.0, 0.0],
        )
        self.assertEqual(ranked[0]["memory_id"], "r2")
        self.assertEqual({item["memory_id"] for item in ranked}, {"r0", "r1", "r2"})

    def test_newest_preserving_budget_restores_chronological_prompt_order(self) -> None:
        records = [
            record("old", 0, "one two three"),
            record("middle", 1, "four five"),
            record("new", 2, "six seven"),
        ]
        selected, usage = core.pack_evidence(
            records,
            lambda text: len(text.split()),
            token_image_budget=4,
            newest_preserving=True,
        )
        self.assertEqual([item["memory_id"] for item in selected], ["middle", "new"])
        self.assertEqual(usage["total_budget_units"], 4)

    def test_multimodal_budget_and_image_cap_are_joint(self) -> None:
        records = [
            record("a", 0, "one", ["i0"]),
            record("b", 1, "two", ["i1"]),
        ]
        selected, usage = core.pack_evidence(
            records,
            lambda text: 1,
            token_image_budget=514,
            image_token_cost=256,
            max_images=1,
        )
        self.assertEqual([item["memory_id"] for item in selected], ["a"])
        self.assertEqual(usage, {"text_tokens": 1, "images": 1, "image_token_cost": 256, "total_budget_units": 257})

    def test_nonfinite_dense_vectors_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite"):
            core.retrieve_control(
                "naive-rag",
                self.records,
                "unused",
                dense_document_vectors=[[1.0, 0.0], [0.0, math.nan], [0.8, 0.2]],
                dense_query_vector=[1.0, 0.0],
            )


if __name__ == "__main__":
    unittest.main()
