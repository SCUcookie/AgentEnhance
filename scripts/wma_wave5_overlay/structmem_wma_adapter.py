"""WorldMemArena adapter for StructMem at the frozen official revision."""

from __future__ import annotations

import importlib
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
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


EXPECTED_SOURCE_REVISION = "aa1c484cc6fd964c8ea1af897e36a0c3ba06d7db"
SUMMARY_LIMIT = 5
SUMMARY_TIME_WINDOW_SECONDS = 3600
SUMMARY_TOP_K_SEEDS = 15


def _required_path(value: str | os.PathLike[str] | None, env_name: str) -> Path:
    raw = str(value or os.getenv(env_name) or "")
    if not raw:
        raise RuntimeError(f"missing required path: {env_name}")
    path = Path(raw).resolve()
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeError(f"{env_name} must resolve to an absolute non-symlink path")
    return path


def _turn_text(turn: NormalizedTurn) -> str:
    parts = [f"original_role={turn.role}", turn.text]
    for attachment in turn.attachments:
        parts.append(
            f"[attachment type={attachment.type} image_id={attachment.image_id or 'none'}] "
            f"{attachment.caption}"
        )
    return "\n".join(part for part in parts if part).strip()


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _point_dict(point: Any) -> dict[str, Any]:
    if isinstance(point, dict):
        return {
            "id": point.get("id"),
            "payload": dict(point.get("payload") or {}),
        }
    return {
        "id": getattr(point, "id"),
        "payload": dict(getattr(point, "payload", {}) or {}),
    }


class StructMemAdapter(MemoryAdapter):
    """Caption-mediated StructMem; final answers remain in the common WMA path."""

    def __init__(
        self,
        *,
        source_root: str | os.PathLike[str] | None = None,
        storage_root: str | os.PathLike[str] | None = None,
        llmlingua_model_path: str | os.PathLike[str] | None = None,
        **_: Any,
    ) -> None:
        self._source_root = _required_path(source_root, "STRUCTMEM_SOURCE_ROOT")
        self._storage_root = _required_path(storage_root, "STRUCTMEM_STORAGE_ROOT")
        self._llmlingua_model_path = _required_path(
            llmlingua_model_path, "STRUCTMEM_LLMLINGUA_MODEL_PATH"
        )
        required_source = (
            self._source_root / "LICENSE",
            self._source_root / "pyproject.toml",
            self._source_root / "src" / "lightmem" / "memory" / "lightmem.py",
            self._source_root / "experiments" / "locomo" / "prompts.py",
        )
        if not all(path.is_file() for path in required_source):
            raise RuntimeError(f"invalid StructMem source: {self._source_root}")
        if any(self._source_root.rglob("*.pyc")):
            raise RuntimeError("StructMem source must not contain bytecode")
        if not (self._llmlingua_model_path / "model.safetensors").is_file():
            raise RuntimeError(
                f"invalid frozen StructMem LLMLingua model: {self._llmlingua_model_path}"
            )

        source_path = str(self._source_root / "src")
        if source_path not in sys.path:
            sys.path.insert(0, source_path)
        self._lightmem_module = importlib.import_module("lightmem.memory.lightmem")
        self._backend_cls = self._lightmem_module.LightMemory
        self._prompts = self._load_prompts()

        self._backend: Any = None
        self._generation = -1
        self._active_storage: Path | None = None
        self._sessions: dict[str, list[NormalizedTurn]] = {}
        self._backend_session_ids: dict[str, str] = {}
        self._previous_snapshot_ids: set[str] = set()
        self._last_assigned_timestamp: datetime | None = None
        self._summary_calls = 0

    def _load_prompts(self) -> dict[str, str]:
        path = self._source_root / "experiments" / "locomo" / "prompts.py"
        spec = importlib.util.spec_from_file_location(
            f"agentenhance_structmem_prompts_{id(self)}", path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load StructMem prompt module: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return {
            "factual": module.LoCoMo_Event_Binding_factual,
            "relational": module.LoCoMo_Event_Binding_relational,
        }

    def _build_config(self, storage: Path) -> dict[str, Any]:
        api_key = os.getenv("OPENAI_API_KEY") or "EMPTY"
        base_url = os.getenv("OPENAI_BASE_URL")
        model = os.getenv("OPENAI_MODEL") or "Qwen3-VL-8B-Instruct"
        embedding_base_url = os.getenv("STRUCTMEM_EMBED_BASE_URL")
        if not base_url or not embedding_base_url:
            raise RuntimeError("OPENAI_BASE_URL and STRUCTMEM_EMBED_BASE_URL are required")
        return {
            "pre_compress": True,
            "pre_compressor": {
                "model_name": "llmlingua-2",
                "configs": {
                    "llmlingua_config": {
                        "model_name": str(self._llmlingua_model_path),
                        "device_map": os.getenv("STRUCTMEM_LLMLINGUA_DEVICE") or "cpu",
                        "use_llmlingua2": True,
                    },
                    "compress_config": {
                        "instruction": "",
                        "rate": 0.6,
                        "target_token": -1,
                    },
                },
            },
            "topic_segment": True,
            "precomp_topic_shared": True,
            "topic_segmenter": {"model_name": "llmlingua-2"},
            "messages_use": "user_only",
            "metadata_generate": True,
            "text_summary": True,
            "memory_manager": {
                "model_name": "openai",
                "configs": {
                    "model": model,
                    "api_key": api_key,
                    "max_tokens": 16000,
                    "temperature": 0.0,
                    "openai_base_url": base_url,
                },
            },
            "extract_threshold": 0.1,
            "index_strategy": "embedding",
            "text_embedder": {
                "model_name": "openai",
                "configs": {
                    "model": "text-embedding-3-small",
                    "api_key": api_key,
                    "openai_base_url": embedding_base_url,
                    "embedding_dims": 384,
                },
            },
            "retrieve_strategy": "embedding",
            "embedding_retriever": {
                "model_name": "qdrant",
                "configs": {
                    "collection_name": "structmem_details",
                    "embedding_model_dims": 384,
                    "path": str(storage / "details"),
                    "on_disk": True,
                },
            },
            "summary_retriever": {
                "model_name": "qdrant",
                "configs": {
                    "collection_name": "structmem_summaries",
                    "embedding_model_dims": 384,
                    "path": str(storage / "summaries"),
                    "on_disk": True,
                },
            },
            "update": "offline",
            "logging": {
                "level": "INFO",
                "file_enabled": True,
                "log_dir": str(storage / "logs"),
            },
            "extraction_mode": "event",
        }

    def _close_backend(self) -> None:
        if self._backend is None:
            return
        for name in ("embedding_retriever", "summary_retriever"):
            retriever = getattr(self._backend, name, None)
            client = getattr(retriever, "client", None)
            close = getattr(client, "close", None)
            if callable(close):
                close()
        self._backend = None

    def _new_backend(self, storage: Path) -> Any:
        return self._backend_cls.from_config(self._build_config(storage))

    def reset(self) -> None:
        self._close_backend()
        self._generation += 1
        storage = self._storage_root / f"generation-{self._generation:03d}"
        if storage.exists():
            raise RuntimeError(f"refusing existing StructMem storage generation: {storage}")
        storage.mkdir(parents=True)
        self._lightmem_module.GLOBAL_TOPIC_IDX = 0
        self._lightmem_module.GLOBAL_LAST_SUMMARY_TIME = None
        self._active_storage = storage
        self._backend = self._new_backend(storage)
        self._sessions = {}
        self._backend_session_ids = {}
        self._previous_snapshot_ids = set()
        self._last_assigned_timestamp = None
        self._summary_calls = 0

    def reload_from_disk(self) -> None:
        if self._active_storage is None:
            raise RuntimeError("StructMem adapter has not been reset")
        self._persist_session_map()
        self._close_backend()
        self._backend = self._new_backend(self._active_storage)
        self._load_session_map()

    def ingest_turn(self, turn: NormalizedTurn) -> None:
        if self._backend is None:
            raise RuntimeError("StructMem adapter must be reset before ingest")
        self._sessions.setdefault(turn.session_id, []).append(turn)

    def _assign_timestamp(self, value: str | None) -> str:
        candidate = _parse_timestamp(value)
        if candidate is None:
            candidate = self._last_assigned_timestamp or datetime(2000, 1, 1)
        if self._last_assigned_timestamp is not None and candidate <= self._last_assigned_timestamp:
            candidate = self._last_assigned_timestamp + timedelta(seconds=1)
        self._last_assigned_timestamp = candidate
        return candidate.isoformat(timespec="seconds")

    def end_session(self, session_id: str) -> None:
        if self._backend is None:
            raise RuntimeError("StructMem adapter must be reset before session end")
        turns = self._sessions.pop(session_id, None)
        if not turns:
            raise RuntimeError(f"StructMem session has no buffered turns: {session_id}")
        for index, turn in enumerate(turns):
            timestamp = self._assign_timestamp(turn.timestamp)
            speaker = str(turn.role)
            messages = [
                {
                    "role": "user",
                    "content": _turn_text(turn),
                    "speaker_id": speaker,
                    "speaker_name": speaker,
                    "time_stamp": timestamp,
                },
                {
                    "role": "assistant",
                    "content": "",
                    "speaker_id": speaker,
                    "speaker_name": speaker,
                    "time_stamp": timestamp,
                },
            ]
            final = index == len(turns) - 1
            self._backend.add_memory(
                messages=messages,
                METADATA_GENERATE_PROMPT=self._prompts,
                force_segment=final,
                force_extract=final,
            )
        self._backend.summarize(
            retrieval_scope="global",
            time_window=SUMMARY_TIME_WINDOW_SECONDS,
            top_k_seeds=SUMMARY_TOP_K_SEEDS,
            process_all=True,
        )
        self._summary_calls += 1
        self._capture_new_ids(session_id)
        self._persist_session_map()

    def _scroll_all(self, retriever: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset: Any = None
        observed: set[str] = set()
        while True:
            points, next_offset = retriever.scroll(
                limit=1000,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                row = _point_dict(point)
                memory_id = str(row["id"])
                if memory_id in observed:
                    raise RuntimeError(f"duplicate StructMem backend id: {memory_id}")
                observed.add(memory_id)
                rows.append(row)
            if next_offset is None:
                break
            if not points or next_offset == offset:
                raise RuntimeError("StructMem pagination failed to advance")
            offset = next_offset
        return rows

    def _backend_rows(self) -> list[tuple[str, dict[str, Any]]]:
        if self._backend is None:
            return []
        rows = [("detail", row) for row in self._scroll_all(self._backend.embedding_retriever)]
        rows.extend(("summary", row) for row in self._scroll_all(self._backend.summary_retriever))
        return rows

    def _capture_new_ids(self, session_id: str) -> None:
        for kind, row in self._backend_rows():
            key = f"{kind}:{row['id']}"
            self._backend_session_ids.setdefault(key, session_id)

    @property
    def _session_map_path(self) -> Path:
        if self._active_storage is None:
            raise RuntimeError("StructMem storage is not active")
        return self._active_storage / "agentenhance-session-map.json"

    def _persist_session_map(self) -> None:
        self._session_map_path.write_text(
            json.dumps(self._backend_session_ids, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _load_session_map(self) -> None:
        self._backend_session_ids = json.loads(self._session_map_path.read_text(encoding="utf-8"))

    def snapshot_memories(self) -> list[MemorySnapshotRecord]:
        rows: list[MemorySnapshotRecord] = []
        for kind, row in self._backend_rows():
            payload = dict(row["payload"])
            memory_id = str(row["id"])
            key = f"{kind}:{memory_id}"
            text = str(payload.get("memory") if kind == "detail" else payload.get("summary") or "")
            rows.append(
                MemorySnapshotRecord(
                    memory_id=key,
                    text=text,
                    session_id=self._backend_session_ids.get(key, ""),
                    status="active",
                    source="StructMem",
                    raw_backend_id=memory_id,
                    raw_backend_type=kind,
                    metadata={
                        **payload,
                        "caption_mediated": True,
                        "original_backend_id": memory_id,
                    },
                )
            )
        return sorted(rows, key=lambda row: row.memory_id)

    def export_memory_delta(self, session_id: str) -> list[MemoryDeltaRecord]:
        snapshot = self.snapshot_memories()
        current_ids = {row.memory_id for row in snapshot}
        deltas = [
            MemoryDeltaRecord(
                session_id=session_id,
                op="add",
                text=row.text,
                raw_backend_id=row.raw_backend_id,
                metadata={"baseline": "StructMem", "backend_type": row.raw_backend_type, **row.metadata},
            )
            for row in snapshot
            if row.memory_id not in self._previous_snapshot_ids
        ]
        self._previous_snapshot_ids = current_ids
        return deltas

    def retrieve(self, query: str, top_k: int, **_: Any) -> RetrievalRecord:
        if self._backend is None:
            raise RuntimeError("StructMem adapter must be reset before retrieval")
        if top_k < 0:
            raise ValueError("top_k must be non-negative")
        query_vector = self._backend.text_embedder.embed(query)
        detail_hits = self._backend.embedding_retriever.search(
            query_vector=query_vector,
            limit=top_k,
            return_full=True,
        )
        summary_quota = min(SUMMARY_LIMIT, top_k)
        summary_hits = self._backend.summary_retriever.search(
            query_vector=query_vector,
            limit=summary_quota,
            return_full=True,
        ) if summary_quota else []
        candidates: list[tuple[str, dict[str, Any]]] = [
            *(('detail', dict(hit)) for hit in detail_hits),
            *(('summary', dict(hit)) for hit in summary_hits),
        ]
        seen: set[str] = set()
        scored: list[tuple[str, dict[str, Any], float]] = []
        for kind, hit in candidates:
            key = f"{kind}:{hit['id']}"
            if key in seen:
                raise RuntimeError(f"duplicate StructMem retrieval id: {key}")
            seen.add(key)
            score = float(hit["score"])
            if not math.isfinite(score):
                raise RuntimeError("StructMem retrieval returned a non-finite score")
            scored.append((kind, hit, score))
        scored.sort(key=lambda item: (-item[2], f"{item[0]}:{item[1]['id']}"))
        selected = scored[:top_k]
        items = []
        for rank, (kind, hit, score) in enumerate(selected):
            payload = dict(hit.get("payload") or {})
            text = str(payload.get("memory") if kind == "detail" else payload.get("summary") or "")
            items.append(
                RetrievalItem(
                    rank=rank,
                    memory_id=f"{kind}:{hit['id']}",
                    text=text,
                    score=score,
                    raw_backend_id=str(hit["id"]),
                )
            )
        return RetrievalRecord(
            query=query,
            top_k=top_k,
            items=items,
            raw_trace={
                "baseline": "StructMem",
                "caption_mediated": True,
                "native_multimodal": False,
                "detail_candidates": len(detail_hits),
                "summary_candidates": len(summary_hits),
                "summary_limit": SUMMARY_LIMIT,
                "returned_count": len(items),
                "summary_calls": self._summary_calls,
                "retrieval_budget_shared": True,
            },
        )

    def close(self) -> None:
        self._close_backend()

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "backend": "StructMem",
            "baseline": "StructMem",
            "available": True,
            "native_multimodal": False,
            "caption_mediated": True,
            "extraction_mode": "event",
            "summary_mode": "incremental_process_all_after_session",
            "summary_time_window_seconds": SUMMARY_TIME_WINDOW_SECONDS,
            "summary_top_k_seeds": SUMMARY_TOP_K_SEEDS,
            "summary_limit": SUMMARY_LIMIT,
            "retrieval_budget_shared": True,
            "global_state_reset": ["GLOBAL_TOPIC_IDX", "GLOBAL_LAST_SUMMARY_TIME"],
        }
