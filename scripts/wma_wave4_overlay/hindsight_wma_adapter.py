"""WorldMemArena adapter for Hindsight 0.9.2's official public API."""

from __future__ import annotations

import atexit
import importlib
import json
import math
import os
import sys
from datetime import datetime
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
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeError(f"{env_name} must resolve to an absolute non-symlink path")
    return path


def _turn_text(turn: NormalizedTurn) -> str:
    parts = [f"{turn.role}: {turn.text}"]
    for attachment in turn.attachments:
        parts.append(
            f"[attachment type={attachment.type} image_id={attachment.image_id or 'none'}] "
            f"{attachment.caption}"
        )
    return "\n".join(part for part in parts if part).strip()


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class HindsightAdapter(MemoryAdapter):
    """Caption-mediated Hindsight memory; final answers remain in the common WMA path."""

    def __init__(
        self,
        *,
        source_root: str | os.PathLike[str] | None = None,
        storage_root: str | os.PathLike[str] | None = None,
        embedding_model_path: str | os.PathLike[str] | None = None,
        reranker_model_path: str | os.PathLike[str] | None = None,
        **_: Any,
    ) -> None:
        self._source_root = _required_path(source_root, "HINDSIGHT_SOURCE_ROOT")
        self._storage_root = _required_path(storage_root, "HINDSIGHT_STORAGE_ROOT")
        self._embedding_model_path = _required_path(
            embedding_model_path, "HINDSIGHT_EMBED_MODEL_PATH"
        )
        self._reranker_model_path = _required_path(
            reranker_model_path, "HINDSIGHT_RERANKER_MODEL_PATH"
        )
        required_source = (
            self._source_root / "hindsight-all" / "hindsight" / "server.py",
            self._source_root
            / "hindsight-clients"
            / "python"
            / "hindsight_client"
            / "hindsight_client.py",
            self._source_root / "hindsight-api-slim" / "hindsight_api" / "config.py",
        )
        if not all(path.is_file() for path in required_source):
            raise RuntimeError(f"invalid Hindsight execution source: {self._source_root}")
        if any(self._source_root.rglob("*.pyc")):
            raise RuntimeError("Hindsight execution source must not contain bytecode")
        for model_path, label in (
            (self._embedding_model_path, "embedding"),
            (self._reranker_model_path, "reranker"),
        ):
            if not (model_path / "model.safetensors").is_file():
                raise RuntimeError(f"invalid frozen Hindsight {label} model: {model_path}")
        if Path.home().resolve() != self._storage_root:
            raise RuntimeError("Hindsight storage_root must equal the process HOME")

        for relative in (
            "hindsight-all",
            "hindsight-api-slim",
            "hindsight-clients/python",
            "hindsight-embed",
        ):
            path = str(self._source_root / relative)
            if path not in sys.path:
                sys.path.insert(0, path)
        module = importlib.import_module("hindsight")
        self._server_cls = module.HindsightServer
        self._client_cls = module.HindsightClient

        expected_environment = {
            "HINDSIGHT_API_EMBEDDINGS_PROVIDER": "local",
            "HINDSIGHT_API_EMBEDDINGS_LOCAL_MODEL": str(self._embedding_model_path),
            "HINDSIGHT_API_EMBEDDINGS_LOCAL_FORCE_CPU": "true",
            "HINDSIGHT_API_EMBEDDINGS_LOCAL_TRUST_REMOTE_CODE": "false",
            "HINDSIGHT_API_RERANKER_PROVIDER": "local",
            "HINDSIGHT_API_RERANKER_LOCAL_MODEL": str(self._reranker_model_path),
            "HINDSIGHT_API_RERANKER_LOCAL_FORCE_CPU": "true",
            "HINDSIGHT_API_RERANKER_LOCAL_TRUST_REMOTE_CODE": "false",
            "HINDSIGHT_API_RERANKER_LOCAL_FP16": "false",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
        mismatches = {
            key: (os.getenv(key), expected)
            for key, expected in expected_environment.items()
            if os.getenv(key) != expected
        }
        if mismatches:
            raise RuntimeError(f"Hindsight frozen environment mismatch: {mismatches}")

        self._server: Any = None
        self._client: Any = None
        self._generation = -1
        self._database_name = ""
        self._bank_id = ""
        self._sessions: dict[str, list[NormalizedTurn]] = {}
        self._previous_snapshot_ids: set[str] = set()
        self._internal_retain_calls = 0
        self._closed = False
        atexit.register(self.close)

    def _new_server(self) -> Any:
        return self._server_cls(
            db_url=f"pg0://{self._database_name}",
            llm_provider="openai",
            llm_api_key=os.getenv("OPENAI_API_KEY") or "EMPTY",
            llm_model=os.getenv("OPENAI_MODEL") or "Qwen3-VL-8B-Instruct",
            llm_base_url=os.getenv("OPENAI_BASE_URL"),
            host="127.0.0.1",
            port=None,
            mcp_enabled=False,
            log_level="warning",
        )

    def _start(self, *, create_bank: bool) -> None:
        self._server = self._new_server().start(timeout=120.0)
        self._client = self._client_cls(base_url=self._server.url, timeout=300.0)
        if create_bank:
            self._client.create_bank(
                bank_id=self._bank_id,
                retain_extraction_mode="concise",
                enable_observations=True,
                enable_text_search=True,
                enable_temporal_retrieval=True,
                enable_graph_retrieval=True,
                enable_reranking=True,
            )

    def _stop(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._server is not None:
            self._server.stop(timeout=30.0)
            self._server = None

    def reset(self) -> None:
        self._stop()
        self._generation += 1
        self._database_name = f"agentenhance-hindsight-g{self._generation:03d}"
        self._bank_id = f"worldmemarena-g{self._generation:03d}"
        database_root = self._storage_root / ".pg0" / "instances" / self._database_name
        if database_root.exists():
            raise RuntimeError(f"refusing existing Hindsight database root: {database_root}")
        self._sessions = {}
        self._previous_snapshot_ids = set()
        self._internal_retain_calls = 0
        self._closed = False
        self._start(create_bank=True)

    def reload_from_disk(self) -> None:
        if not self._database_name or self._client is None:
            raise RuntimeError("Hindsight adapter has not been reset")
        self._stop()
        self._start(create_bank=False)

    def ingest_turn(self, turn: NormalizedTurn) -> None:
        if self._client is None:
            raise RuntimeError("Hindsight adapter must be reset before ingest")
        self._sessions.setdefault(turn.session_id, []).append(turn)

    def end_session(self, session_id: str) -> None:
        if self._client is None:
            raise RuntimeError("Hindsight adapter must be reset before session end")
        turns = self._sessions.pop(session_id, None)
        if not turns or len(turns) % 2:
            raise RuntimeError(f"Hindsight session has incomplete turn pairs: {session_id}")
        items = []
        for index in range(0, len(turns), 2):
            user, assistant = turns[index : index + 2]
            if user.role != "user" or assistant.role != "assistant":
                raise RuntimeError("Hindsight requires ordered user/assistant pairs")
            if user.session_id != session_id or assistant.session_id != session_id:
                raise RuntimeError("Hindsight pair crosses a session boundary")
            image_ids = [
                attachment.image_id
                for turn in (user, assistant)
                for attachment in turn.attachments
                if attachment.image_id
            ]
            items.append(
                {
                    "content": f"{_turn_text(user)}\n{_turn_text(assistant)}",
                    "timestamp": _timestamp(user.timestamp or assistant.timestamp),
                    "context": f"WorldMemArena session={session_id} pair={index // 2}",
                    "metadata": {
                        "wma_session_id": session_id,
                        "wma_sample_id": user.sample_id,
                        "wma_image_ids": json.dumps(image_ids, separators=(",", ":")),
                        "caption_mediated": "true",
                    },
                    "tags": [f"wma-session:{session_id}"],
                }
            )
        response = self._client.retain_batch(
            bank_id=self._bank_id,
            items=items,
            document_id=session_id,
            document_tags=[f"wma-session:{session_id}"],
            retain_async=False,
        )
        if not response.success or response.var_async or response.items_count != len(items):
            raise RuntimeError("Hindsight retain_batch did not synchronously accept every pair")
        self._internal_retain_calls += 1

    def snapshot_memories(self) -> list[MemorySnapshotRecord]:
        if self._client is None:
            return []
        rows: list[MemorySnapshotRecord] = []
        offset = 0
        expected_total: int | None = None
        observed_ids: set[str] = set()
        while True:
            page = self._client.list_memories(
                bank_id=self._bank_id,
                limit=100,
                offset=offset,
            )
            if expected_total is None:
                expected_total = page.total
            elif page.total != expected_total:
                raise RuntimeError("Hindsight memory total changed during pagination")
            for item in page.items:
                metadata = dict(item.get("metadata") or {})
                memory_id = str(item["id"])
                if memory_id in observed_ids:
                    raise RuntimeError(f"duplicate Hindsight memory id: {memory_id}")
                observed_ids.add(memory_id)
                rows.append(
                    MemorySnapshotRecord(
                        memory_id=memory_id,
                        text=str(item["text"]),
                        session_id=str(metadata.get("wma_session_id") or item.get("document_id") or ""),
                        status="active",
                        source="Hindsight",
                        raw_backend_id=memory_id,
                        raw_backend_type=str(item.get("type") or "unknown"),
                        metadata={
                            **metadata,
                            "context": item.get("context"),
                            "occurred_start": item.get("occurred_start") or item.get("date"),
                            "occurred_end": item.get("occurred_end"),
                            "mentioned_at": item.get("mentioned_at"),
                            "document_id": item.get("document_id"),
                            "tags": item.get("tags") or [],
                            "caption_mediated": True,
                        },
                    )
                )
            offset += len(page.items)
            if offset >= page.total:
                break
            if not page.items:
                raise RuntimeError("Hindsight pagination stopped before total was exhausted")
        if len(rows) != expected_total:
            raise RuntimeError("Hindsight snapshot cardinality does not match reported total")
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
                metadata={"baseline": "Hindsight", **row.metadata},
            )
            for row in snapshot
            if row.memory_id not in self._previous_snapshot_ids
        ]
        self._previous_snapshot_ids = current_ids
        return deltas

    def retrieve(self, query: str, top_k: int, **_: Any) -> RetrievalRecord:
        if self._client is None:
            raise RuntimeError("Hindsight adapter must be reset before retrieval")
        response = self._client.recall(
            bank_id=self._bank_id,
            query=query,
            max_tokens=4096,
            budget="mid",
            trace=True,
        )
        items = []
        score_rows = []
        for rank, result in enumerate(response.results[:top_k]):
            if result.scores is None:
                raise RuntimeError("Hindsight recall result is missing official scores")
            scores = result.scores.model_dump(exclude_none=True)
            score = float(scores["final"])
            if not math.isfinite(score):
                raise RuntimeError("Hindsight recall returned a non-finite final score")
            items.append(
                RetrievalItem(
                    rank=rank,
                    memory_id=str(result.id),
                    text=str(result.text),
                    score=score,
                    raw_backend_id=str(result.id),
                )
            )
            score_rows.append(scores)
        return RetrievalRecord(
            query=query,
            top_k=top_k,
            items=items,
            raw_trace={
                "baseline": "Hindsight",
                "caption_mediated": True,
                "native_multimodal": False,
                "recall_budget": "mid",
                "max_tokens": 4096,
                "trace_enabled": True,
                "backend_result_count": len(response.results),
                "returned_result_count": len(items),
                "official_scores": score_rows,
                "backend_trace": response.trace,
                "internal_retain_calls": self._internal_retain_calls,
                "reflect_called": False,
            },
        )

    def close(self) -> None:
        if self._closed:
            return
        self._stop()
        self._closed = True

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "backend": "Hindsight",
            "baseline": "Hindsight",
            "available": True,
            "native_multimodal": False,
            "caption_mediated": True,
            "snapshot_mode": "paginated_official_list_memories",
            "delta_granularity": "backend_memory_id",
            "retrieval_score": "RecallScores.final",
            "reflect_excluded": True,
            "official_retrieval_arms": ["semantic", "text", "temporal", "graph", "reranker"],
        }
