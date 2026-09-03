"""WorldMemArena adapter for the immutable MemoryOS pypi implementation."""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from eval_framework.datasets.schemas import (
    MemoryDeltaRecord,
    MemorySnapshotRecord,
    NormalizedTurn,
    RetrievalItem,
    RetrievalRecord,
)
from eval_framework.memory_adapters.base import MemoryAdapter


_ERROR_MARKERS = (
    "Error in retrieval task",
    "Error in parallel LLM processing",
    "Error generating embedding",
    "Error saving",
    "Error decoding JSON",
    "unexpected error",
)


def _required_path(value: str | os.PathLike[str] | None, env_name: str) -> Path:
    raw = str(value or os.getenv(env_name) or "")
    if not raw:
        raise RuntimeError(f"missing required path: {env_name}")
    path = Path(raw).resolve()
    if not path.is_absolute():
        raise RuntimeError(f"{env_name} must resolve to an absolute path")
    return path


def _stable_id(prefix: str, payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(encoded).hexdigest()[:20]}"


def _turn_text(turn: NormalizedTurn) -> str:
    parts = [turn.text]
    for attachment in turn.attachments:
        image_id = attachment.image_id or "none"
        parts.append(
            f"[attachment type={attachment.type} image_id={image_id}] "
            f"{attachment.caption}"
        )
    return "\n".join(part for part in parts if part).strip()


class MemoryOSAdapter(MemoryAdapter):
    """Expose MemoryOS retrieval while leaving final answer generation to WMA."""

    def __init__(
        self,
        *,
        source_root: str | os.PathLike[str] | None = None,
        storage_root: str | os.PathLike[str] | None = None,
        embedding_model_path: str | os.PathLike[str] | None = None,
        **_: Any,
    ) -> None:
        self._source_root = _required_path(source_root, "MEMORYOS_SOURCE_ROOT")
        self._storage_root = _required_path(storage_root, "MEMORYOS_STORAGE_ROOT")
        self._embedding_model_path = _required_path(
            embedding_model_path, "MEMORYOS_EMBED_MODEL_PATH"
        )
        if not (self._source_root / "memoryos.py").is_file():
            raise RuntimeError(f"invalid MemoryOS source root: {self._source_root}")
        if not (self._embedding_model_path / "model.safetensors").is_file():
            raise RuntimeError(
                f"invalid frozen MemoryOS embedding snapshot: {self._embedding_model_path}"
            )

        package_parent = str(self._source_root.parent)
        if package_parent not in sys.path:
            sys.path.insert(0, package_parent)
        package_name = self._source_root.name
        memoryos_module = importlib.import_module(f"{package_name}.memoryos")
        updater_module = importlib.import_module(f"{package_name}.updater")
        utils_module = importlib.import_module(f"{package_name}.utils")
        self._backend_cls = memoryos_module.Memoryos
        self._install_embedding_path_overlay(updater_module.Updater, utils_module)

        self._backend: Any = None
        self._generation = -1
        self._active_storage: Path | None = None
        self._pending_user: NormalizedTurn | None = None
        self._current_session = ""
        self._source_sessions: dict[str, str] = {}
        self._previous_snapshot_ids: set[str] = set()
        self._backend_log: list[str] = []

    @staticmethod
    def _install_embedding_path_overlay(updater_cls: type, utils_module: Any) -> None:
        if getattr(updater_cls, "_agentenhance_embedding_overlay", False):
            return

        def _configured_page_embedding(updater: Any, text: str) -> Any:
            memory = updater.mid_term_memory
            return utils_module.get_embedding(
                text,
                model_name=memory.embedding_model_name,
                **memory.embedding_model_kwargs,
            )

        updater_cls._get_embedding_for_page = _configured_page_embedding
        updater_cls._agentenhance_embedding_overlay = True

    def _call(self, operation: str, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            result = function(*args, **kwargs)
        output = stream.getvalue()
        if output:
            print(output, end="", flush=True)
            self._backend_log.append(output)
        if any(marker.lower() in output.lower() for marker in _ERROR_MARKERS):
            raise RuntimeError(f"MemoryOS reported a swallowed error during {operation}")
        return result

    def _new_backend(self, storage: Path) -> Any:
        return self._backend_cls(
            user_id="worldmemarena-user",
            assistant_id="worldmemarena-assistant",
            openai_api_key=os.getenv("OPENAI_API_KEY") or "EMPTY",
            openai_base_url=os.getenv("OPENAI_BASE_URL"),
            data_storage_path=str(storage),
            llm_model=os.getenv("OPENAI_MODEL") or "Qwen3-VL-8B-Instruct",
            embedding_model_name=str(self._embedding_model_path),
            embedding_model_kwargs={
                "device": os.getenv("MEMORYOS_EMBED_DEVICE") or "cpu"
            },
        )

    def reset(self) -> None:
        self._generation += 1
        storage = self._storage_root / f"generation-{self._generation:03d}"
        if storage.exists():
            raise RuntimeError(f"refusing existing MemoryOS storage generation: {storage}")
        storage.mkdir(parents=True)
        self._active_storage = storage
        self._backend = self._call("construct", self._new_backend, storage)
        self._pending_user = None
        self._current_session = ""
        self._source_sessions = {}
        self._previous_snapshot_ids = set()
        self._backend_log = []

    def reload_from_disk(self) -> None:
        if self._active_storage is None:
            raise RuntimeError("MemoryOS adapter has not been reset")
        self._backend = self._call(
            "reload_from_disk", self._new_backend, self._active_storage
        )

    def ingest_turn(self, turn: NormalizedTurn) -> None:
        if self._backend is None:
            raise RuntimeError("MemoryOS adapter must be reset before ingest")
        self._current_session = turn.session_id
        if turn.role == "user":
            if self._pending_user is not None:
                raise RuntimeError("MemoryOS received consecutive user turns")
            self._pending_user = turn
            return
        if turn.role != "assistant":
            raise RuntimeError(f"MemoryOS unsupported role: {turn.role}")
        if self._pending_user is None:
            raise RuntimeError("MemoryOS received an assistant turn without a user turn")
        user_turn = self._pending_user
        if user_turn.session_id != turn.session_id:
            raise RuntimeError("MemoryOS user/assistant pair crosses a session boundary")
        user_text = _turn_text(user_turn)
        assistant_text = _turn_text(turn)
        timestamp = user_turn.timestamp or turn.timestamp
        self._call(
            "add_memory",
            self._backend.add_memory,
            user_input=user_text,
            agent_response=assistant_text,
            timestamp=timestamp,
        )
        key = _stable_id("pair", [user_text, assistant_text, timestamp])
        self._source_sessions[key] = turn.session_id
        self._pending_user = None

    def end_session(self, session_id: str) -> None:
        if self._pending_user is not None:
            raise RuntimeError(
                f"MemoryOS session {session_id} ended with an incomplete user/assistant pair"
            )
        self._current_session = session_id

    def _pair_session(self, row: dict[str, Any]) -> str:
        key = _stable_id(
            "pair",
            [row.get("user_input", ""), row.get("agent_response", ""), row.get("timestamp")],
        )
        return self._source_sessions.get(key, self._current_session)

    def snapshot_memories(self) -> list[MemorySnapshotRecord]:
        if self._backend is None:
            return []
        rows: list[MemorySnapshotRecord] = []
        for item in self._backend.short_term_memory.get_all():
            memory_id = _stable_id("memoryos-short", item)
            rows.append(
                MemorySnapshotRecord(
                    memory_id=memory_id,
                    text=(
                        f"User: {item.get('user_input', '')}\n"
                        f"Assistant: {item.get('agent_response', '')}"
                    ),
                    session_id=self._pair_session(item),
                    status="active",
                    source="MemoryOS",
                    raw_backend_id=memory_id,
                    raw_backend_type="short_term_qa",
                    metadata={"layer": "short_term", "caption_mediated": True},
                )
            )
        for segment_id, segment in self._backend.mid_term_memory.sessions.items():
            for item in segment.get("details", []):
                page_id = str(item.get("page_id") or _stable_id("memoryos-page", item))
                rows.append(
                    MemorySnapshotRecord(
                        memory_id=page_id,
                        text=(
                            f"User: {item.get('user_input', '')}\n"
                            f"Assistant: {item.get('agent_response', '')}\n"
                            f"Context: {item.get('meta_info') or ''}"
                        ).strip(),
                        session_id=self._pair_session(item),
                        status="active",
                        source="MemoryOS",
                        raw_backend_id=page_id,
                        raw_backend_type="mid_term_page",
                        metadata={
                            "layer": "mid_term",
                            "segment_id": str(segment_id),
                            "caption_mediated": True,
                        },
                    )
                )
        profile = self._backend.user_long_term_memory.get_user_profile_data(
            self._backend.user_id
        )
        if profile.get("data"):
            memory_id = _stable_id("memoryos-profile", profile)
            rows.append(
                MemorySnapshotRecord(
                    memory_id=memory_id,
                    text=str(profile["data"]),
                    session_id=self._current_session,
                    status="active",
                    source="MemoryOS",
                    raw_backend_id=memory_id,
                    raw_backend_type="long_term_user_profile",
                    metadata={"layer": "long_term", "provenance": "derived"},
                )
            )
        for kind, items in (
            ("user_knowledge", self._backend.user_long_term_memory.get_user_knowledge()),
            ("assistant_knowledge", self._backend.assistant_long_term_memory.get_assistant_knowledge()),
        ):
            for item in items:
                memory_id = _stable_id(f"memoryos-{kind}", item)
                rows.append(
                    MemorySnapshotRecord(
                        memory_id=memory_id,
                        text=str(item.get("knowledge", "")),
                        session_id=self._current_session,
                        status="active",
                        source="MemoryOS",
                        raw_backend_id=memory_id,
                        raw_backend_type=f"long_term_{kind}",
                        metadata={"layer": "long_term", "provenance": "derived"},
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
                metadata={"baseline": "MemoryOS", **row.metadata},
            )
            for row in snapshot
            if row.memory_id not in self._previous_snapshot_ids
        ]
        self._previous_snapshot_ids = current_ids
        return deltas

    def retrieve(self, query: str, top_k: int, **_: Any) -> RetrievalRecord:
        if self._backend is None:
            raise RuntimeError("MemoryOS adapter must be reset before retrieval")
        result = self._call(
            "retrieve_context",
            self._backend.retriever.retrieve_context,
            user_query=query,
            user_id=self._backend.user_id,
        )
        candidates: list[tuple[str, str, str]] = []
        short = self._backend.short_term_memory.get_all()
        if short:
            text = "\n\n".join(
                f"User: {row.get('user_input', '')}\nAssistant: {row.get('agent_response', '')}"
                for row in short
            )
            candidates.append(("memoryos-short-history", text, "short_term_history"))
        for row in result["retrieved_pages"]:
            candidates.append(
                (
                    str(row.get("page_id") or _stable_id("memoryos-page", row)),
                    (
                        f"User: {row.get('user_input', '')}\n"
                        f"Assistant: {row.get('agent_response', '')}\n"
                        f"Context: {row.get('meta_info') or ''}"
                    ).strip(),
                    "mid_term_page",
                )
            )
        for kind, key in (
            ("long_term_user_knowledge", "retrieved_user_knowledge"),
            ("long_term_assistant_knowledge", "retrieved_assistant_knowledge"),
        ):
            for row in result[key]:
                candidates.append(
                    (
                        _stable_id(f"memoryos-{kind}", row),
                        str(row.get("knowledge", "")),
                        kind,
                    )
                )
        items = [
            RetrievalItem(
                rank=rank,
                memory_id=memory_id,
                text=text,
                score=1.0 / (rank + 1),
                raw_backend_id=memory_id,
            )
            for rank, (memory_id, text, _kind) in enumerate(candidates[:top_k])
        ]
        return RetrievalRecord(
            query=query,
            top_k=top_k,
            items=items,
            raw_trace={
                "baseline": "MemoryOS",
                "caption_mediated": True,
                "query_mutates_mid_term_access_state": True,
                "score_semantics": "synthetic reciprocal backend rank; official API strips raw scores",
                "short_term_pairs": len(short),
                "mid_term_pages": len(result["retrieved_pages"]),
                "user_knowledge": len(result["retrieved_user_knowledge"]),
                "assistant_knowledge": len(result["retrieved_assistant_knowledge"]),
                "swallowed_error_detected": False,
            },
        )

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "backend": "MemoryOS",
            "baseline": "MemoryOS",
            "available": True,
            "native_multimodal": False,
            "caption_mediated": True,
            "query_is_stateful": True,
            "snapshot_mode": "all_backend_layers",
            "delta_granularity": "snapshot_diff",
            "embedding_path_overlay": True,
        }
