"""WorldMemArena adapter for the immutable MemGAS quickstart implementation."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

from eval_framework.datasets.schemas import (
    MemoryDeltaRecord,
    MemorySnapshotRecord,
    NormalizedTurn,
    RetrievalItem,
    RetrievalRecord,
)
from eval_framework.memory_adapters.base import MemoryAdapter


def _required_path(value: str | os.PathLike[str] | None, env_name: str) -> Path:
    raw = str(value or os.getenv(env_name) or "")
    if not raw:
        raise RuntimeError(f"missing required path: {env_name}")
    path = Path(raw).resolve()
    if not path.is_absolute():
        raise RuntimeError(f"{env_name} must resolve to an absolute path")
    return path


def _turn_text(turn: NormalizedTurn) -> str:
    parts = [f"{turn.role}: {turn.text}"]
    for attachment in turn.attachments:
        image_id = attachment.image_id or "none"
        parts.append(
            f"[attachment type={attachment.type} image_id={image_id}] "
            f"{attachment.caption}"
        )
    return "\n".join(part for part in parts if part).strip()


class MemGASAdapter(MemoryAdapter):
    def __init__(
        self,
        *,
        source_root: str | os.PathLike[str] | None = None,
        storage_root: str | os.PathLike[str] | None = None,
        embedding_model_path: str | os.PathLike[str] | None = None,
        **_: Any,
    ) -> None:
        self._source_root = _required_path(source_root, "MEMGAS_SOURCE_ROOT")
        self._storage_root = _required_path(storage_root, "MEMGAS_STORAGE_ROOT")
        self._embedding_model_path = _required_path(
            embedding_model_path, "MEMGAS_CONTRIEVER_MODEL_PATH"
        )
        if any(self._source_root.rglob("*.pyc")):
            raise RuntimeError("MemGAS execution source must not contain bytecode")
        if not (self._source_root / "quickstart" / "memory.py").is_file():
            raise RuntimeError(f"invalid MemGAS execution source: {self._source_root}")
        if not (self._embedding_model_path / "pytorch_model.bin").is_file():
            raise RuntimeError(f"invalid frozen Contriever snapshot: {self._embedding_model_path}")
        source_text = str(self._source_root)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)

        self._fallback_events: list[dict[str, str]] = []
        config_module = importlib.import_module("quickstart.config")
        embedder_module = importlib.import_module("quickstart.embedder")
        retriever_module = importlib.import_module("quickstart.retriever")
        memory_module = importlib.import_module("quickstart.memory")
        self._install_model_path_overlay(embedder_module)
        self._install_gmm_audit_overlay(retriever_module)
        self._config_cls = config_module.MemoryConfig
        self._backend_cls = memory_module.MemGASMemory

        self._backend: Any = None
        self._generation = -1
        self._active_storage: Path | None = None
        self._sessions: dict[str, list[str]] = {}
        self._session_metadata: dict[str, list[dict[str, Any]]] = {}
        self._previous_snapshot_ids: set[str] = set()

    def _install_model_path_overlay(self, module: Any) -> None:
        if getattr(module, "_agentenhance_model_path_overlay", False):
            return
        original_model = module.AutoModel
        original_tokenizer = module.AutoTokenizer
        model_path = str(self._embedding_model_path)

        class PinnedAutoModel:
            @classmethod
            def from_pretrained(cls, name: str, *args: Any, **kwargs: Any) -> Any:
                if name != "facebook/contriever":
                    raise RuntimeError(f"unexpected MemGAS model request: {name}")
                kwargs["local_files_only"] = True
                return original_model.from_pretrained(model_path, *args, **kwargs)

        class PinnedAutoTokenizer:
            @classmethod
            def from_pretrained(cls, name: str, *args: Any, **kwargs: Any) -> Any:
                if name != "facebook/contriever":
                    raise RuntimeError(f"unexpected MemGAS tokenizer request: {name}")
                kwargs["local_files_only"] = True
                return original_tokenizer.from_pretrained(model_path, *args, **kwargs)

        module.AutoModel = PinnedAutoModel
        module.AutoTokenizer = PinnedAutoTokenizer
        module._agentenhance_model_path_overlay = True

    def _install_gmm_audit_overlay(self, module: Any) -> None:
        module._agentenhance_gmm_events = self._fallback_events
        if getattr(module, "_agentenhance_gmm_audit_overlay", False):
            return
        original_gmm = module.GaussianMixture

        class AuditedGaussianMixture:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self._inner = original_gmm(*args, **kwargs)

            def fit(self, *args: Any, **kwargs: Any) -> Any:
                try:
                    self._inner.fit(*args, **kwargs)
                    return self
                except Exception as exc:
                    module._agentenhance_gmm_events.append(
                        {"operation": "fit", "error": f"{type(exc).__name__}: {exc}"}
                    )
                    raise

            def predict(self, *args: Any, **kwargs: Any) -> Any:
                try:
                    return self._inner.predict(*args, **kwargs)
                except Exception as exc:
                    module._agentenhance_gmm_events.append(
                        {"operation": "predict", "error": f"{type(exc).__name__}: {exc}"}
                    )
                    raise

            def __getattr__(self, name: str) -> Any:
                return getattr(self._inner, name)

        module.GaussianMixture = AuditedGaussianMixture
        module._agentenhance_gmm_audit_overlay = True

    def _new_backend(self, storage: Path) -> Any:
        config = self._config_cls(
            storage_dir=str(storage),
            embedder="contriever",
            device=os.getenv("MEMGAS_EMBED_DEVICE") or "cpu",
            batch_size=64,
            llm_model=os.getenv("OPENAI_MODEL") or "Qwen3-VL-8B-Instruct",
            llm_provider="vllm",
            llm_api_key=os.getenv("OPENAI_API_KEY") or "EMPTY",
            llm_base_url=os.getenv("OPENAI_BASE_URL"),
            llm_max_tokens=500,
            llm_temperature=0.0,
            llm_max_retries=3,
            llm_retry_wait_sec=2.0,
            default_mode="memgas",
            mem_threshold=30,
            n_components=2,
            num_seednodes=15,
            damping=0.1,
            router_temp=0.2,
            auto_save=True,
        )
        return self._backend_cls(config)

    def reset(self) -> None:
        self._generation += 1
        storage = self._storage_root / f"generation-{self._generation:03d}"
        if storage.exists():
            raise RuntimeError(f"refusing existing MemGAS storage generation: {storage}")
        storage.mkdir(parents=True)
        self._active_storage = storage
        self._fallback_events.clear()
        self._backend = self._new_backend(storage)
        self._sessions = {}
        self._session_metadata = {}
        self._previous_snapshot_ids = set()

    def reload_from_disk(self) -> None:
        if self._active_storage is None:
            raise RuntimeError("MemGAS adapter has not been reset")
        self._backend = self._new_backend(self._active_storage)

    def ingest_turn(self, turn: NormalizedTurn) -> None:
        if self._backend is None:
            raise RuntimeError("MemGAS adapter must be reset before ingest")
        self._sessions.setdefault(turn.session_id, []).append(_turn_text(turn))
        self._session_metadata.setdefault(turn.session_id, []).append(
            {
                "sample_id": turn.sample_id,
                "turn_index": turn.turn_index,
                "role": turn.role,
                "timestamp": turn.timestamp,
                "image_ids": [item.image_id for item in turn.attachments if item.image_id],
            }
        )

    def end_session(self, session_id: str) -> None:
        turns = self._sessions.pop(session_id, None)
        metadata = self._session_metadata.pop(session_id, None)
        if not turns or metadata is None:
            raise RuntimeError(f"MemGAS session has no buffered turns: {session_id}")
        self._backend.add(
            turns,
            conversation_id=session_id,
            metadata={
                "wma_session_id": session_id,
                "wma_source_turns": metadata,
                "caption_mediated": True,
            },
        )

    def snapshot_memories(self) -> list[MemorySnapshotRecord]:
        if self._backend is None:
            return []
        rows = []
        for record in self._backend.store.records:
            text = (
                f"Summary: {record.summary}\n"
                f"Keywords: {'; '.join(record.keywords)}\n"
                + "\n".join(record.session)
            ).strip()
            rows.append(
                MemorySnapshotRecord(
                    memory_id=str(record.memory_id),
                    text=text,
                    session_id=str(record.conversation_id),
                    status="active",
                    source="MemGAS",
                    raw_backend_id=str(record.memory_id),
                    raw_backend_type="multigranular_session",
                    metadata={
                        **dict(record.metadata),
                        "embedding_granularities": list(self._backend.store.EMBED_KEYS),
                    },
                )
            )
        return rows

    def export_memory_delta(self, session_id: str) -> list[MemoryDeltaRecord]:
        snapshot = self.snapshot_memories()
        current_ids = {row.memory_id for row in snapshot}
        deltas = [
            MemoryDeltaRecord(
                session_id=session_id,
                op="add",
                text=row.text,
                raw_backend_id=row.raw_backend_id,
                metadata={"baseline": "MemGAS", **row.metadata},
            )
            for row in snapshot
            if row.memory_id not in self._previous_snapshot_ids
        ]
        self._previous_snapshot_ids = current_ids
        return deltas

    def retrieve(self, query: str, top_k: int, **_: Any) -> RetrievalRecord:
        if self._backend is None:
            raise RuntimeError("MemGAS adapter must be reset before retrieval")
        fallback_before = len(self._fallback_events)
        hits = self._backend.retrieve(
            query,
            topk=top_k,
            conversation_id=None,
            mode="memgas",
        )
        items = [
            RetrievalItem(
                rank=rank,
                memory_id=str(hit["memory_id"]),
                text=(
                    f"Summary: {hit['summary']}\n"
                    f"Keywords: {'; '.join(hit['keywords'])}\n"
                    + "\n".join(hit["session"])
                ).strip(),
                score=float(hit["score"]),
                raw_backend_id=str(hit["memory_id"]),
            )
            for rank, hit in enumerate(hits)
        ]
        return RetrievalRecord(
            query=query,
            top_k=top_k,
            items=items,
            raw_trace={
                "baseline": "MemGAS",
                "mode": "memgas",
                "caption_mediated": True,
                "gmm_fallback_count_query": len(self._fallback_events) - fallback_before,
                "gmm_fallback_count_total": len(self._fallback_events),
                "gmm_fallback_events": list(self._fallback_events[fallback_before:]),
                "granularity_scores": [hit["granularity_scores"] for hit in hits],
            },
        )

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "backend": "MemGAS",
            "baseline": "MemGAS",
            "available": True,
            "native_multimodal": False,
            "caption_mediated": True,
            "snapshot_mode": "stored_multigranular_sessions",
            "delta_granularity": "backend_memory_id",
            "embedding_path_overlay": True,
            "gmm_fallback_audit_overlay": True,
        }
