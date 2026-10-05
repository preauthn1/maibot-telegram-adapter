from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.A_memorix.host_service import a_memorix_host_service
from src.common.logger import get_logger
from src.common.utils.prompt_time import format_prompt_timestamp


logger = get_logger("memory_service")


def _format_memory_epoch(value: Any) -> str:
    """将记忆时间戳格式化为北京时间（UTC+8）分钟级文本；无效值返回空串。"""

    if value is None or isinstance(value, bool):
        return ""
    try:
        return format_prompt_timestamp(float(value), "%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def format_memory_time_label(metadata: Any) -> str:
    """根据命中 metadata.time_meta 生成模型可见的时间标注（审计 F11）。

    区分事件发生时间与入库时间；仅按入库时间回退匹配时明确告知事件时间未知，
    避免模型把入库日期当成事件日期。
    """

    if not isinstance(metadata, dict):
        return ""
    time_meta = metadata.get("time_meta")
    if not isinstance(time_meta, dict):
        return ""
    parts: List[str] = []
    event_start = _format_memory_epoch(time_meta.get("event_time_start"))
    event_end = _format_memory_epoch(time_meta.get("event_time_end"))
    event_point = _format_memory_epoch(time_meta.get("event_time"))
    if event_start or event_end:
        parts.append(f"事件时间 {event_start or '?'} 至 {event_end or '?'}")
    elif event_point:
        parts.append(f"事件时间 {event_point}")
    ingest_text = _format_memory_epoch(time_meta.get("ingest_time"))
    if ingest_text:
        parts.append(f"入库 {ingest_text}")
    match_basis = str(time_meta.get("match_basis") or "").strip()
    if match_basis == "created_at_fallback":
        parts.append("仅按入库时间匹配，事件发生时间未知")
    elif match_basis in {"event_time", "event_time_range"}:
        parts.append("匹配依据：事件时间")
    if not parts:
        return ""
    parts.append("北京时间")
    return f"（{'，'.join(parts)}）"


@dataclass
class MemoryHit:
    content: str
    score: float = 0.0
    hit_type: str = ""
    source: str = ""
    hash_value: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    episode_id: str = ""
    title: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "score": self.score,
            "type": self.hit_type,
            "source": self.source,
            "hash": self.hash_value,
            "metadata": self.metadata,
            "episode_id": self.episode_id,
            "title": self.title,
        }


@dataclass
class MemorySearchResult:
    summary: str = ""
    hits: List[MemoryHit] = field(default_factory=list)
    filtered: bool = False
    success: bool = True
    error: str = ""

    def to_text(self, limit: int = 5, *, truncate_content: bool = True, max_content_chars: int = 160, preserve_whitespace: bool = False) -> str:
        if not self.hits:
            return ""
        lines = []
        for index, item in enumerate(self.hits[: max(1, int(limit))], start=1):
            # 工具正文需要原始段落/代码结构，默认预览仍维持既有单行行为。
            content = item.content if preserve_whitespace else item.content.strip().replace("\n", " ")
            if truncate_content and len(content) > max_content_chars:
                content = content[:max_content_chars] + "..."
            # 附带事件/入库时间标注，避免模型混淆两者（审计 F11）。
            lines.append(f"{index}. {content}{format_memory_time_label(item.metadata)}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "error": self.error,
            "summary": self.summary,
            "hits": [item.to_dict() for item in self.hits],
            "filtered": self.filtered,
        }


@dataclass
class MemoryWriteResult:
    success: bool
    stored_ids: List[str] = field(default_factory=list)
    skipped_ids: List[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "stored_ids": self.stored_ids,
            "skipped_ids": self.skipped_ids,
            "detail": self.detail,
        }


@dataclass
class PersonProfileResult:
    summary: str = ""
    traits: List[str] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"summary": self.summary, "traits": self.traits, "evidence": self.evidence}


class MemoryService:
    async def _invoke(
        self,
        component_name: str,
        args: Optional[Dict[str, Any]] = None,
        *,
        timeout_ms: Optional[int] = None,
    ) -> Any:
        if timeout_ms is None:
            response = await a_memorix_host_service.invoke(component_name, args or {})
        else:
            response = await a_memorix_host_service.invoke(component_name, args or {}, timeout_ms=timeout_ms)
        if isinstance(response, dict):
            return response
        payload = getattr(response, "payload", None)
        if isinstance(payload, dict):
            if isinstance(payload.get("result"), dict):
                return payload["result"]
            return payload
        model_dump = getattr(response, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                inner_payload = dumped.get("payload")
                if isinstance(inner_payload, dict):
                    if isinstance(inner_payload.get("result"), dict):
                        return inner_payload["result"]
                    return inner_payload
        return response

    async def _invoke_admin(
        self,
        component_name: str,
        *,
        action: str,
        timeout_ms: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        if timeout_ms is None:
            payload = await self._invoke(component_name, {"action": action, **kwargs})
        else:
            payload = await self._invoke(component_name, {"action": action, **kwargs}, timeout_ms=timeout_ms)
        return payload if isinstance(payload, dict) else {"success": False, "error": "invalid_payload"}

    @staticmethod
    def _coerce_write_result(payload: Any) -> MemoryWriteResult:
        if not isinstance(payload, dict):
            return MemoryWriteResult(success=False, detail="invalid_payload")
        stored_ids = [str(item) for item in (payload.get("stored_ids") or []) if str(item).strip()]
        skipped_ids = [str(item) for item in (payload.get("skipped_ids") or []) if str(item).strip()]
        detail = str(payload.get("detail") or payload.get("reason") or "")
        if stored_ids or skipped_ids:
            success = True
        elif "success" in payload:
            success = bool(payload.get("success"))
        else:
            success = not bool(detail)
        return MemoryWriteResult(
            success=success,
            stored_ids=stored_ids,
            skipped_ids=skipped_ids,
            detail=detail,
        )

    @staticmethod
    def _coerce_search_result(payload: Any) -> MemorySearchResult:
        if not isinstance(payload, dict):
            return MemorySearchResult(success=False, error="invalid_payload")
        # 显式状态只接受JSON布尔值；缺字段的旧后端仍由error判断。
        if "success" in payload and type(payload["success"]) is not bool:
            return MemorySearchResult(success=False, error="invalid_success_type")
        # 过滤标志同样只接受布尔值，不能将字符串false解释为策略跳过。
        if "filtered" in payload and type(payload["filtered"]) is not bool:
            return MemorySearchResult(success=False, error="invalid_filtered_type")
        raw_hits = payload.get("hits")
        # 缺字段/null沿用旧后端空结果约定；损坏结构不能伪装成零命中。
        if raw_hits is None:
            raw_hits = []
        if not isinstance(raw_hits, list) or any(not isinstance(item, dict) for item in raw_hits):
            return MemorySearchResult(success=False, error="invalid_hits_shape")
        hits: List[MemoryHit] = []
        for item in raw_hits:
            metadata = item.get("metadata", {}) or {}
            if not isinstance(metadata, dict):
                metadata = {}
            metadata = dict(metadata)
            if "source_branches" in item and "source_branches" not in metadata:
                metadata["source_branches"] = item.get("source_branches") or []
            if "rank" in item and "rank" not in metadata:
                metadata["rank"] = item.get("rank")
            # 嵌套来源字段也隔离，避免消费方修改反向污染后端payload或其他结果。
            metadata = deepcopy(metadata)
            hits.append(
                MemoryHit(
                    content=str(item.get("content", "") or ""),
                    score=float(item.get("score", 0.0) or 0.0),
                    hit_type=str(item.get("type", "") or ""),
                    source=str(item.get("source", "") or ""),
                    hash_value=str(item.get("hash", "") or ""),
                    metadata=metadata,
                    episode_id=str(item.get("episode_id", "") or ""),
                    title=str(item.get("title", "") or ""),
                )
            )
        success_raw = payload.get("success")
        error = str(payload.get("error", "") or "")
        # 非空error与success=true矛盾时按失败处理，不让残留命中进入对话。
        success = not bool(error) and (success_raw is None or success_raw is True)
        return MemorySearchResult(
            summary=str(payload.get("summary", "") or ""),
            hits=hits,
            filtered=bool(payload.get("filtered", False)),
            success=success,
            error=error,
        )

    @staticmethod
    def _coerce_profile_result(payload: Any) -> PersonProfileResult:
        if not isinstance(payload, dict):
            return PersonProfileResult()
        return PersonProfileResult(
            summary=str(payload.get("summary", "") or ""),
            traits=[str(item) for item in (payload.get("traits") or []) if str(item).strip()],
            evidence=[item for item in (payload.get("evidence") or []) if isinstance(item, dict)],
        )

    async def search(
        self,
        query: str,
        *,
        limit: int = 5,
        mode: str = "search",
        chat_id: str = "",
        person_id: str = "",
        time_start: str | float | None = None,
        time_end: str | float | None = None,
        respect_filter: bool = True,
        user_id: str = "",
        group_id: str = "",
    ) -> MemorySearchResult:
        clean_query = str(query or "").strip()
        normalized_time_start = None if time_start in {None, ""} else time_start
        normalized_time_end = None if time_end in {None, ""} else time_end
        if not clean_query and normalized_time_start is None and normalized_time_end is None:
            return MemorySearchResult()
        try:
            payload = await self._invoke(
                "search_memory",
                {
                    "query": clean_query,
                    "limit": max(1, int(limit)),
                    "mode": mode,
                    "chat_id": chat_id,
                    "person_id": person_id,
                    "time_start": normalized_time_start,
                    "time_end": normalized_time_end,
                    "respect_filter": bool(respect_filter),
                    "user_id": str(user_id or "").strip(),
                    "group_id": str(group_id or "").strip(),
                },
            )
            result = self._coerce_search_result(payload)
            if not result.success:
                # 失败payload的摘要/命中也可能是诊断内容，不当作可信记忆向上传递。
                logger.warning("长期记忆搜索返回失败结果")
                return MemorySearchResult(success=False, error="长期记忆检索失败；暂不能确认是否存在相关记忆。")
            if result.filtered:
                # 策略跳过的响应不应携带可供回复器消费的残留摘要或命中。
                return MemorySearchResult(success=True, filtered=True)
            return result
        except Exception as exc:
            # 服务层异常原文可能含后端凭据；工具层拿到失败结果也不应再暴露它。
            logger.warning(f"长期记忆搜索失败: {type(exc).__name__}")
            return MemorySearchResult(success=False, error="长期记忆检索失败；暂不能确认是否存在相关记忆。")

    async def enqueue_feedback_task(
        self,
        *,
        query_tool_id: str,
        session_id: str,
        query_timestamp: Any = None,
        structured_content: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            payload = await self._invoke(
                "enqueue_feedback_task",
                {
                    "query_tool_id": str(query_tool_id or "").strip(),
                    "session_id": str(session_id or "").strip(),
                    "query_timestamp": query_timestamp,
                    "structured_content": structured_content if isinstance(structured_content, dict) else {},
                },
                timeout_ms=10000,
            )
        except Exception as exc:
            logger.warning(f"反馈纠错任务入队失败: {exc}")
            return {"success": False, "queued": False, "reason": str(exc)}
        return (
            payload if isinstance(payload, dict) else {"success": False, "queued": False, "reason": "invalid_payload"}
        )

    async def ingest_summary(
        self,
        *,
        external_id: str,
        chat_id: str,
        text: str,
        participants: Optional[List[str]] = None,
        time_start: float | None = None,
        time_end: float | None = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        respect_filter: bool = True,
        user_id: str = "",
        group_id: str = "",
    ) -> MemoryWriteResult:
        try:
            payload = await self._invoke(
                "ingest_summary",
                {
                    "external_id": external_id,
                    "chat_id": chat_id,
                    "text": text,
                    "participants": participants or [],
                    "time_start": time_start,
                    "time_end": time_end,
                    "tags": tags or [],
                    "metadata": metadata or {},
                    "respect_filter": bool(respect_filter),
                    "user_id": str(user_id or "").strip(),
                    "group_id": str(group_id or "").strip(),
                },
            )
            return self._coerce_write_result(payload)
        except Exception as exc:
            logger.warning(f"长期记忆写入摘要失败: {exc}")
            return MemoryWriteResult(success=False, detail=str(exc))

    async def ingest_text(
        self,
        *,
        external_id: str,
        source_type: str,
        text: str,
        chat_id: str = "",
        person_ids: Optional[List[str]] = None,
        participants: Optional[List[str]] = None,
        timestamp: float | None = None,
        time_start: float | None = None,
        time_end: float | None = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        entities: Optional[List[str]] = None,
        relations: Optional[List[Dict[str, Any]]] = None,
        respect_filter: bool = True,
        user_id: str = "",
        group_id: str = "",
    ) -> MemoryWriteResult:
        try:
            payload = await self._invoke(
                "ingest_text",
                {
                    "external_id": external_id,
                    "source_type": source_type,
                    "text": text,
                    "chat_id": chat_id,
                    "person_ids": person_ids or [],
                    "participants": participants or [],
                    "timestamp": timestamp,
                    "time_start": time_start,
                    "time_end": time_end,
                    "tags": tags or [],
                    "metadata": metadata or {},
                    "entities": entities or [],
                    "relations": relations or [],
                    "respect_filter": bool(respect_filter),
                    "user_id": str(user_id or "").strip(),
                    "group_id": str(group_id or "").strip(),
                },
            )
            return self._coerce_write_result(payload)
        except Exception as exc:
            logger.warning(f"长期记忆写入文本失败: {exc}")
            return MemoryWriteResult(success=False, detail=str(exc))

    async def get_person_profile(self, person_id: str, *, chat_id: str = "", limit: int = 10) -> PersonProfileResult:
        clean_person_id = str(person_id or "").strip()
        if not clean_person_id:
            return PersonProfileResult()
        try:
            payload = await self._invoke(
                "get_person_profile",
                {"person_id": clean_person_id, "chat_id": chat_id, "limit": max(1, int(limit))},
            )
            return self._coerce_profile_result(payload)
        except Exception as exc:
            logger.warning(f"获取人物画像失败: {exc}")
            return PersonProfileResult()

    async def maintain_memory(
        self,
        *,
        action: str,
        target: str = "",
        hours: float | None = None,
        reason: str = "",
        limit: int = 50,
    ) -> MemoryWriteResult:
        try:
            payload = await self._invoke(
                "maintain_memory",
                {"action": action, "target": target, "hours": hours, "reason": reason, "limit": limit},
            )
            if not isinstance(payload, dict):
                return MemoryWriteResult(success=False, detail="invalid_payload")
            return MemoryWriteResult(success=bool(payload.get("success")), detail=str(payload.get("detail", "") or ""))
        except Exception as exc:
            logger.warning(f"记忆维护失败: {exc}")
            return MemoryWriteResult(success=False, detail=str(exc))

    async def memory_stats(self) -> Dict[str, Any]:
        try:
            payload = await self._invoke("memory_stats", {})
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            logger.warning(f"获取记忆统计失败: {exc}")
            return {}

    async def image_memory(self, *, action: str, timeout_ms: int = 120000, **kwargs: Any) -> Dict[str, Any]:
        """调用图片记忆的写入、相似检索和管理接口。"""

        try:
            payload = await self._invoke(
                "image_memory",
                {"action": str(action or "").strip(), **kwargs},
                timeout_ms=timeout_ms,
            )
            return payload if isinstance(payload, dict) else {"success": False, "error": "invalid_payload"}
        except Exception as exc:
            logger.warning(f"图片记忆调用失败: {exc}")
            return {"success": False, "error": str(exc)}

    async def graph_admin(self, *, action: str, **kwargs) -> Dict[str, Any]:
        try:
            return await self._invoke_admin("memory_graph_admin", action=action, **kwargs)
        except Exception as exc:
            logger.warning(f"图谱管理调用失败: {exc}")
            return {"success": False, "error": str(exc)}

    async def source_admin(self, *, action: str, **kwargs) -> Dict[str, Any]:
        try:
            return await self._invoke_admin("memory_source_admin", action=action, **kwargs)
        except Exception as exc:
            logger.warning(f"来源管理调用失败: {exc}")
            return {"success": False, "error": str(exc)}

    async def episode_admin(self, *, action: str, **kwargs) -> Dict[str, Any]:
        try:
            return await self._invoke_admin("memory_episode_admin", action=action, **kwargs)
        except Exception as exc:
            logger.warning(f"Episode 管理调用失败: {exc}")
            return {"success": False, "error": str(exc)}

    async def profile_admin(self, *, action: str, **kwargs) -> Dict[str, Any]:
        try:
            return await self._invoke_admin("memory_profile_admin", action=action, **kwargs)
        except Exception as exc:
            error = f"profile_admin_failed:{type(exc).__name__}"
            logger.warning(f"画像管理调用失败: {error}")
            return {"success": False, "error": error}

    async def feedback_admin(self, *, action: str, **kwargs) -> Dict[str, Any]:
        try:
            return await self._invoke_admin("memory_feedback_admin", action=action, **kwargs)
        except Exception as exc:
            logger.warning(f"反馈纠错管理调用失败: {exc}")
            return {"success": False, "error": str(exc)}

    async def fact_admin(self, *, action: str, **kwargs) -> Dict[str, Any]:
        try:
            return await self._invoke_admin("memory_fact_admin", action=action, **kwargs)
        except Exception as exc:
            logger.warning(f"事实账本管理调用失败: {exc}")
            return {"success": False, "error": str(exc)}

    async def runtime_admin(self, *, action: str, **kwargs) -> Dict[str, Any]:
        try:
            return await self._invoke_admin("memory_runtime_admin", action=action, **kwargs)
        except Exception as exc:
            logger.warning(f"运行时管理调用失败: {exc}")
            return {"success": False, "error": str(exc)}

    async def import_admin(self, *, action: str, timeout_ms: int = 120000, **kwargs) -> Dict[str, Any]:
        try:
            return await self._invoke_admin("memory_import_admin", action=action, timeout_ms=timeout_ms, **kwargs)
        except Exception as exc:
            logger.warning(f"导入管理调用失败: {exc}")
            return {"success": False, "error": str(exc)}

    async def bundle_admin(self, *, action: str, timeout_ms: int = 120000, **kwargs) -> Dict[str, Any]:
        try:
            return await self._invoke_admin("memory_bundle_admin", action=action, timeout_ms=timeout_ms, **kwargs)
        except Exception as exc:
            logger.warning(f"记忆包管理调用失败: {exc}")
            return {"success": False, "error": str(exc)}

    async def tuning_admin(self, *, action: str, timeout_ms: int = 120000, **kwargs) -> Dict[str, Any]:
        try:
            return await self._invoke_admin("memory_tuning_admin", action=action, timeout_ms=timeout_ms, **kwargs)
        except Exception as exc:
            logger.warning(f"调优管理调用失败: {exc}")
            return {"success": False, "error": str(exc)}

    async def v5_admin(self, *, action: str, timeout_ms: Optional[int] = None, **kwargs) -> Dict[str, Any]:
        try:
            return await self._invoke_admin("memory_v5_admin", action=action, timeout_ms=timeout_ms, **kwargs)
        except Exception as exc:
            logger.warning(f"V5 记忆管理调用失败: {exc}")
            return {"success": False, "error": str(exc)}

    async def delete_admin(self, *, action: str, timeout_ms: int = 120000, **kwargs) -> Dict[str, Any]:
        try:
            return await self._invoke_admin("memory_delete_admin", action=action, timeout_ms=timeout_ms, **kwargs)
        except Exception as exc:
            logger.warning(f"删除管理调用失败: {exc}")
            return {"success": False, "error": str(exc)}

    async def memory_correction_admin(self, *, action: str, timeout_ms: int = 120000, **kwargs) -> Dict[str, Any]:
        try:
            return await self._invoke_admin("memory_correction_admin", action=action, timeout_ms=timeout_ms, **kwargs)
        except Exception as exc:
            logger.warning(f"记忆修正管理调用失败: {exc}")
            return {"success": False, "error": str(exc)}

    async def fuzzy_modify_admin(self, *, action: str, timeout_ms: int = 120000, **kwargs) -> Dict[str, Any]:
        return await self.memory_correction_admin(action=action, timeout_ms=timeout_ms, **kwargs)

    async def get_recycle_bin(self, *, limit: int = 50) -> Dict[str, Any]:
        try:
            payload = await self._invoke(
                "maintain_memory", {"action": "recycle_bin", "limit": max(1, int(limit or 50))}
            )
            return payload if isinstance(payload, dict) else {"success": False, "error": "invalid_payload"}
        except Exception as exc:
            logger.warning(f"获取回收站失败: {exc}")
            return {"success": False, "error": str(exc)}

    async def restore_memory(self, *, target: str) -> MemoryWriteResult:
        return await self.maintain_memory(action="restore", target=target)

    async def reinforce_memory(self, *, target: str) -> MemoryWriteResult:
        return await self.maintain_memory(action="reinforce", target=target)

    async def freeze_memory(self, *, target: str) -> MemoryWriteResult:
        return await self.maintain_memory(action="freeze", target=target)

    async def protect_memory(self, *, target: str, hours: float | None = None) -> MemoryWriteResult:
        return await self.maintain_memory(action="protect", target=target, hours=hours)


memory_service = MemoryService()
