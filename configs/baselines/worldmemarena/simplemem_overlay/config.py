"""Environment-only SimpleMem configuration for WorldMemArena reproduction.

This module intentionally contains no credentials.  Put its directory before the
frozen SimpleMem source tree on ``PYTHONPATH`` so the bundled code can keep its
upstream ``import config`` statements without modifying the source checkout.
"""

from __future__ import annotations

import os
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "EMPTY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:18120/v1")
LLM_MODEL = os.getenv("OPENAI_MODEL", "Qwen3-VL-8B-Instruct")

EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSION = _int("SIMPLEMEM_EMBEDDING_DIMENSION", 1024)
EMBEDDING_CONTEXT_LENGTH = _int("SIMPLEMEM_EMBEDDING_CONTEXT_LENGTH", 32768)

ENABLE_THINKING = _bool("SIMPLEMEM_ENABLE_THINKING", False)
USE_STREAMING = _bool("SIMPLEMEM_USE_STREAMING", False)
USE_JSON_FORMAT = _bool("SIMPLEMEM_USE_JSON_FORMAT", False)

# Algorithm defaults are copied from the frozen SimpleMem config.py.example.
WINDOW_SIZE = _int("SIMPLEMEM_WINDOW_SIZE", 40)
OVERLAP_SIZE = _int("SIMPLEMEM_OVERLAP_SIZE", 2)
SEMANTIC_TOP_K = _int("SIMPLEMEM_SEMANTIC_TOP_K", 25)
KEYWORD_TOP_K = _int("SIMPLEMEM_KEYWORD_TOP_K", 5)
STRUCTURED_TOP_K = _int("SIMPLEMEM_STRUCTURED_TOP_K", 5)

LANCEDB_PATH = os.getenv(
    "SIMPLEMEM_LANCEDB_PATH",
    str(Path(os.getenv("TMPDIR", "/tmp")) / "agentenhance-simplemem-lancedb"),
)
MEMORY_TABLE_NAME = os.getenv("SIMPLEMEM_MEMORY_TABLE_NAME", "memory_entries")

ENABLE_PARALLEL_PROCESSING = _bool("SIMPLEMEM_ENABLE_PARALLEL_PROCESSING", True)
MAX_PARALLEL_WORKERS = _int("SIMPLEMEM_MAX_PARALLEL_WORKERS", 16)
ENABLE_PARALLEL_RETRIEVAL = _bool("SIMPLEMEM_ENABLE_PARALLEL_RETRIEVAL", True)
MAX_RETRIEVAL_WORKERS = _int("SIMPLEMEM_MAX_RETRIEVAL_WORKERS", 8)

ENABLE_PLANNING = _bool("SIMPLEMEM_ENABLE_PLANNING", True)
ENABLE_REFLECTION = _bool("SIMPLEMEM_ENABLE_REFLECTION", True)
MAX_REFLECTION_ROUNDS = _int("SIMPLEMEM_MAX_REFLECTION_ROUNDS", 2)

JUDGE_API_KEY = os.getenv("JUDGE_API_KEY", OPENAI_API_KEY)
JUDGE_BASE_URL = os.getenv("JUDGE_BASE_URL", OPENAI_BASE_URL)
JUDGE_MODEL = os.getenv("JUDGE_MODEL", LLM_MODEL)
JUDGE_ENABLE_THINKING = False
JUDGE_USE_STREAMING = False
JUDGE_TEMPERATURE = 0.0
