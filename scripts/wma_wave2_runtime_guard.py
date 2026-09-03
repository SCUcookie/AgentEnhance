#!/usr/bin/env python3
"""Fail-closed runtime profiles and endpoint guards for WMA Wave-2 methods."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


PROFILES: dict[str, dict[str, Any]] = {
    "MGMemory": {
        "slug": "mgmemory",
        "service_profile": "text384",
        "primary_embedding_model": "text-embedding-3-small",
        "primary_embedding_dim": 384,
        "aux_embedding_dim": 1024,
    },
    "A-Mem": {
        "slug": "a_mem",
        "service_profile": "text384",
        "primary_embedding_model": "text-embedding-3-small",
        "primary_embedding_dim": 384,
        "aux_embedding_dim": 1024,
    },
    "Omni-SimpleMem": {
        "slug": "omni_simplemem",
        "service_profile": "text1024",
        "primary_embedding_model": "text-embedding-3-small",
        "primary_embedding_dim": 1024,
        "aux_embedding_dim": 384,
    },
    "MIRIX": {
        "slug": "mirix",
        "service_profile": "text1536",
        "primary_embedding_model": "text-embedding-3-small",
        "primary_embedding_dim": 1536,
        "aux_embedding_dim": 384,
        "mirix_endpoint_patch": True,
    },
    "NGMemory": {
        "slug": "ngmemory",
        "service_profile": "gme1536",
        "primary_embedding_model": "gme-Qwen2-VL-2B-Instruct",
        "primary_embedding_dim": 1536,
        "aux_embedding_dim": 384,
        "gme": True,
    },
    "AUGUSTUSMemory": {
        "slug": "augustus",
        "service_profile": "gme1536",
        "primary_embedding_model": "gme-Qwen2-VL-2B-Instruct",
        "primary_embedding_dim": 1536,
        "aux_embedding_dim": 384,
        "gme": True,
    },
    "UniversalRAGMemory": {
        "slug": "universalrag",
        "service_profile": "gme1536",
        "primary_embedding_model": "gme-Qwen2-VL-2B-Instruct",
        "primary_embedding_dim": 1536,
        "aux_embedding_dim": 384,
        "gme": True,
    },
    "Qwen3-VL-Embedding-8B": {
        "slug": "qwen3_vl_embedding_8b",
        "service_profile": "qwen4096",
        "primary_embedding_model": "Qwen3-VL-Embedding-8B",
        "primary_embedding_dim": 4096,
        "aux_embedding_dim": 384,
        "qwen_vl": True,
    },
}

EXPECTED_CHAT_URL = "http://127.0.0.1:18220/v1"
EXPECTED_PRIMARY_EMBED_URL = "http://127.0.0.1:18221/v1"
EXPECTED_AUX_EMBED_URL = "http://127.0.0.1:18222/v1"


def profile_for(baseline: str) -> dict[str, Any]:
    try:
        return {"baseline": baseline, **PROFILES[baseline]}
    except KeyError as exc:
        raise ValueError(f"unsupported Wave-2 baseline: {baseline}") from exc


def validate_runtime_environment(
    baseline: str, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    profile = profile_for(baseline)
    required_exact = {
        "OPENAI_MODEL": "Qwen3-VL-8B-Instruct",
        "OPENAI_BASE_URL": EXPECTED_CHAT_URL,
        "OPENAI_EMBEDDING_BASE_URL": EXPECTED_PRIMARY_EMBED_URL,
        "OPENAI_EMBEDDING_MODEL": profile["primary_embedding_model"],
        "LOCAL_EMBEDDING_DIMS": str(profile["primary_embedding_dim"]),
    }
    for key, expected in required_exact.items():
        observed = env.get(key)
        if observed != expected:
            raise RuntimeError(f"{key} mismatch: expected {expected!r}, got {observed!r}")
    if profile.get("gme"):
        for key, expected in {
            "GME_BASE_URL": EXPECTED_PRIMARY_EMBED_URL,
            "GME_MODEL": "gme-Qwen2-VL-2B-Instruct",
        }.items():
            if env.get(key) != expected:
                raise RuntimeError(f"{key} mismatch: expected {expected!r}")
    if profile.get("qwen_vl"):
        for key, expected in {
            "QWEN_VL_EMBED_BASE_URL": EXPECTED_PRIMARY_EMBED_URL,
            "QWEN_VL_EMBED_MODEL": "Qwen3-VL-Embedding-8B",
            "QWEN_VL_EMBED_REMOTE_IMAGES": "1",
        }.items():
            if env.get(key) != expected:
                raise RuntimeError(f"{key} mismatch: expected {expected!r}")
    return profile


def mirix_embedding_config_kwargs(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    endpoint = env.get("OPENAI_EMBEDDING_BASE_URL")
    model = env.get("OPENAI_EMBEDDING_MODEL")
    dimension = env.get("LOCAL_EMBEDDING_DIMS")
    if endpoint != EXPECTED_PRIMARY_EMBED_URL:
        raise RuntimeError("MIRIX embedding endpoint is not the frozen local endpoint")
    if model != "text-embedding-3-small" or dimension != "1536":
        raise RuntimeError("MIRIX requires text-embedding-3-small with 1536 dimensions")
    return {
        "embedding_model": model,
        "embedding_endpoint_type": "openai",
        "embedding_endpoint": endpoint,
        "embedding_dim": 1536,
        "embedding_chunk_size": 8191,
    }


def apply_mirix_endpoint_patch(environ: Mapping[str, str] | None = None) -> None:
    env = os.environ if environ is None else environ
    repo = Path(env.get("AGENTENHANCE_WMA_REPO", "")).resolve()
    source = repo / "eval_framework" / "baselines" / "MIRIX"
    if not (source / "mirix" / "schemas" / "embedding_config.py").is_file():
        raise RuntimeError(f"missing frozen MIRIX source under {source}")
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

    from mirix.schemas.embedding_config import EmbeddingConfig
    import mirix.embeddings as mirix_embeddings

    kwargs = mirix_embedding_config_kwargs(env)
    original_default = EmbeddingConfig.default_config
    original_factory = mirix_embeddings.embedding_model

    @classmethod
    def guarded_default(cls: type[Any], model_name: str | None = None, provider: str | None = None):
        if model_name == "text-embedding-3-small" or (
            model_name is None and provider == "openai"
        ):
            return cls(**kwargs)
        return original_default(model_name=model_name, provider=provider)

    def guarded_factory(config: Any, user_id: Any = None):
        if config.embedding_endpoint_type != "openai":
            return original_factory(config, user_id=user_id)
        from llama_index.embeddings.openai import OpenAIEmbedding
        from mirix.settings import model_settings

        additional_kwargs = {"user_id": user_id} if user_id else {}
        return OpenAIEmbedding(
            model=config.embedding_model,
            api_base=config.embedding_endpoint,
            api_key=model_settings.openai_api_key,
            additional_kwargs=additional_kwargs,
        )

    EmbeddingConfig.default_config = guarded_default
    mirix_embeddings.embedding_model = guarded_factory
    os.environ["AGENTENHANCE_MIRIX_ENDPOINT_GUARD_ACTIVE"] = "1"
    print(
        "AGENTENHANCE_MIRIX_ENDPOINT_GUARD_ACTIVE="
        + json.dumps(kwargs, sort_keys=True),
        flush=True,
    )


def apply_runtime_guard(baseline: str) -> dict[str, Any]:
    profile = validate_runtime_environment(baseline)
    if profile.get("mirix_endpoint_patch"):
        apply_mirix_endpoint_patch()
    marker = {
        "baseline": baseline,
        "service_profile": profile["service_profile"],
        "primary_embedding_dim": profile["primary_embedding_dim"],
        "qwen_remote_images": os.getenv("QWEN_VL_EMBED_REMOTE_IMAGES")
        if profile.get("qwen_vl")
        else None,
    }
    print("AGENTENHANCE_WAVE2_RUNTIME_GUARD=" + json.dumps(marker, sort_keys=True), flush=True)
    return profile


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    describe = subparsers.add_parser("describe")
    describe.add_argument("--baseline", required=True)
    validate = subparsers.add_parser("validate-env")
    validate.add_argument("--baseline", required=True)
    args = parser.parse_args()
    if args.command == "describe":
        print(json.dumps(profile_for(args.baseline), sort_keys=True))
    else:
        print(json.dumps(validate_runtime_environment(args.baseline), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
