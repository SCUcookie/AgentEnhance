from __future__ import annotations

import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class Wave2RuntimeGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = importlib.import_module("wma_wave2_runtime_guard")

    def environment_for(self, baseline: str) -> dict[str, str]:
        profile = self.guard.profile_for(baseline)
        env = {
            "OPENAI_MODEL": "Qwen3-VL-8B-Instruct",
            "OPENAI_BASE_URL": self.guard.EXPECTED_CHAT_URL,
            "OPENAI_EMBEDDING_BASE_URL": self.guard.EXPECTED_PRIMARY_EMBED_URL,
            "OPENAI_EMBEDDING_MODEL": profile["primary_embedding_model"],
            "LOCAL_EMBEDDING_DIMS": str(profile["primary_embedding_dim"]),
        }
        if profile.get("gme"):
            env.update(
                GME_BASE_URL=self.guard.EXPECTED_PRIMARY_EMBED_URL,
                GME_MODEL="gme-Qwen2-VL-2B-Instruct",
            )
        if profile.get("qwen_vl"):
            env.update(
                QWEN_VL_EMBED_BASE_URL=self.guard.EXPECTED_PRIMARY_EMBED_URL,
                QWEN_VL_EMBED_MODEL="Qwen3-VL-Embedding-8B",
                QWEN_VL_EMBED_REMOTE_IMAGES="1",
            )
        return env

    def test_all_eight_profiles_validate_exact_runtime(self) -> None:
        self.assertEqual(len(self.guard.PROFILES), 8)
        for baseline in self.guard.PROFILES:
            profile = self.guard.validate_runtime_environment(
                baseline, self.environment_for(baseline)
            )
            self.assertEqual(profile["baseline"], baseline)

    def test_qwen_remote_image_omission_is_rejected(self) -> None:
        env = self.environment_for("Qwen3-VL-Embedding-8B")
        del env["QWEN_VL_EMBED_REMOTE_IMAGES"]
        with self.assertRaises(RuntimeError):
            self.guard.validate_runtime_environment("Qwen3-VL-Embedding-8B", env)

    def test_gme_cannot_fall_back_to_qwen_endpoint_identity(self) -> None:
        env = self.environment_for("NGMemory")
        env["GME_MODEL"] = "Qwen3-VL-Embedding-8B"
        with self.assertRaises(RuntimeError):
            self.guard.validate_runtime_environment("NGMemory", env)

    def test_mirix_config_is_local_and_1536_dimensional(self) -> None:
        kwargs = self.guard.mirix_embedding_config_kwargs(
            self.environment_for("MIRIX")
        )
        self.assertEqual(kwargs["embedding_endpoint"], self.guard.EXPECTED_PRIMARY_EMBED_URL)
        self.assertEqual(kwargs["embedding_model"], "text-embedding-3-small")
        self.assertEqual(kwargs["embedding_dim"], 1536)

    def test_mirix_patch_forwards_model_and_endpoint(self) -> None:
        class FakeEmbeddingConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

            @classmethod
            def default_config(cls, model_name=None, provider=None):
                return cls(model_name=model_name, provider=provider, original=True)

        class FakeOpenAIEmbedding:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_modules = {
            "mirix": types.ModuleType("mirix"),
            "mirix.schemas": types.ModuleType("mirix.schemas"),
            "mirix.schemas.embedding_config": types.ModuleType(
                "mirix.schemas.embedding_config"
            ),
            "mirix.embeddings": types.ModuleType("mirix.embeddings"),
            "mirix.settings": types.ModuleType("mirix.settings"),
            "llama_index": types.ModuleType("llama_index"),
            "llama_index.embeddings": types.ModuleType("llama_index.embeddings"),
            "llama_index.embeddings.openai": types.ModuleType(
                "llama_index.embeddings.openai"
            ),
        }
        fake_modules["mirix"].__path__ = []
        fake_modules["mirix.schemas"].__path__ = []
        fake_modules["llama_index"].__path__ = []
        fake_modules["llama_index.embeddings"].__path__ = []
        fake_modules["mirix.schemas.embedding_config"].EmbeddingConfig = FakeEmbeddingConfig
        fake_modules["mirix.embeddings"].embedding_model = lambda config, user_id=None: None
        fake_modules["mirix.settings"].model_settings = types.SimpleNamespace(
            openai_api_key="EMPTY"
        )
        fake_modules["llama_index.embeddings.openai"].OpenAIEmbedding = FakeOpenAIEmbedding

        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            marker = repo / "eval_framework/baselines/MIRIX/mirix/schemas/embedding_config.py"
            marker.parent.mkdir(parents=True)
            marker.write_text("# fixture\n", encoding="utf-8")
            env = self.environment_for("MIRIX")
            env["AGENTENHANCE_WMA_REPO"] = str(repo)
            with mock.patch.dict(sys.modules, fake_modules, clear=False), mock.patch.dict(
                os.environ, {}, clear=False
            ):
                self.guard.apply_mirix_endpoint_patch(env)
                config = FakeEmbeddingConfig.default_config("text-embedding-3-small")
                client = fake_modules["mirix.embeddings"].embedding_model(config)
                self.assertEqual(config.embedding_endpoint, self.guard.EXPECTED_PRIMARY_EMBED_URL)
                self.assertEqual(client.kwargs["model"], "text-embedding-3-small")
                self.assertEqual(client.kwargs["api_base"], self.guard.EXPECTED_PRIMARY_EMBED_URL)

    def test_gme_server_guard_relaxes_only_stale_transformers_bound(self) -> None:
        module = importlib.import_module("run_vllm_gme_guarded")

        def rejecting(requirement: str, hint: str | None = None) -> None:
            del hint
            raise ImportError(requirement)

        guarded = module.build_guarded_require_version(rejecting)
        guarded("transformers<4.52.0")
        with self.assertRaises(ImportError):
            guarded("torch<2.0")


if __name__ == "__main__":
    unittest.main()
