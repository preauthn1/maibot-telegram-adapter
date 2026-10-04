"""自建功能的只读磁盘快照；不导入适配器或启动机器人运行时。"""
from __future__ import annotations

from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Response

import json
import math
import os
import re
import stat

from src.webui.dependencies import require_auth

router = APIRouter(
    prefix="/api/webui/custom-features", tags=["自建功能只读观察"], dependencies=[Depends(require_auth)]
)
_PROJECT = Path(__file__).resolve().parents[3]
_DATA = _PROJECT / "data/plugins/preauthn1.telegram-user-adapter"
_MAX_FILE = 262144
_MAX_TAIL = 131072
_MAX_GROUPS = 64
_MAX_ENTRIES = 256
_GROUP = re.compile(r"-[0-9]+(?:::tg-topic::mt=[0-9]+)?\Z")
_TRANSCRIPT = re.compile(r"chat_-[0-9]+(?:__tg-topic__mt_[0-9]+)?\.jsonl\Z")
_FIELDS = {
    "style_enabled", "manual_style_enabled", "allow_emoji_only", "max_emoji",
    "preserve_trailing_period", "style_max_chars", "style_owner_samples",
    "peer_style_samples", "peer_median_chars", "peer_question_rate", "style_source",
}
_EVENTS = {
    "share_guard_drop": "话语占比 / 投诉静默拦截",
    "consecutive_limit_drop": "连续回复上限",
    "quiet_hours_drop": "出站静默时段",
    "quiet_hours_inbound_drop": "入站静默时段",
    "ai_doubt_silence_started": "投诉静默窗口开始",
    "spam_dropped": "广告拦截",
    "nsfw_dropped": "不当内容拦截",
    "user_flood_ignored": "单用户频率拦截",
    "self_violation": "自省越界记录",
}


def _time(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _alias(chat_id: str) -> str:
    # 认证管理页保留业务群号，便于操作员对应实际聊天；不回传成员/消息。
    return "群 " + chat_id


def _open_directory(path: Path) -> int:
    """逐层拒绝符号链接，目录和文件均不允许跳出固定读取范围。"""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except OSError:
        os.close(fd)
        raise


def _read(path: Path, *, tail: bool = False) -> Tuple[Dict[str, Any], Optional[str]]:
    """调用方仅传固定文件或严格匹配的群文件；无路径参数 API。"""
    parent_fd = None
    fd = None
    try:
        parent_fd = _open_directory(path.parent)
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return {"status": "unsafe", "message": "拒绝非普通文件"}, None
        metadata = {"status": "ok", "bytes": info.st_size, "modified_at": _time(info.st_mtime)}
        if not tail and info.st_size > _MAX_FILE:
            return {**metadata, "status": "oversize", "message": "文件超过 256 KiB，未读取"}, None
        limit = _MAX_TAIL if tail else _MAX_FILE
        offset = max(0, info.st_size - limit) if tail else 0
        os.lseek(fd, offset, os.SEEK_SET)
        with os.fdopen(fd, "rb") as handle:
            fd = None
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            return {**metadata, "status": "changed", "message": "读取期间文件变化，请重新获取"}, None
        if offset:
            # 起点可能落在 UTF-8 或 JSON 行中间，丢弃首个不完整行。
            raw = raw.partition(b"\n")[2]
        metadata["tail_only"] = offset > 0
        return metadata, raw.decode("utf-8")
    except FileNotFoundError:
        return {"status": "missing", "message": "未发现产物"}, None
    except UnicodeDecodeError:
        return {"status": "invalid", "message": "文件不是有效 UTF-8"}, None
    except OSError:
        return {"status": "unreadable", "message": "文件不可读或路径不安全"}, None
    finally:
        if fd is not None:
            os.close(fd)
        if parent_fd is not None:
            os.close(parent_fd)


def _entries(path: Path) -> Tuple[List[str], str, bool]:
    fd = None
    try:
        fd = _open_directory(path)
        with os.scandir(fd) as iterator:
            entries = [entry.name for entry in islice(iterator, _MAX_ENTRIES + 1)]
        return sorted(entries[:_MAX_ENTRIES]), "ok", len(entries) > _MAX_ENTRIES
    except FileNotFoundError:
        return [], "missing", False
    except OSError:
        return [], "unreadable", False
    finally:
        if fd is not None:
            os.close(fd)


def _frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """只投影生成器的已知标量，重复/非法键值不猜测归属。"""
    match = re.match(r"\A---[^\S\r\n]*\r?\n(.*?)\r?\n---[^\S\r\n]*(?:\r?\n|$)", text, re.S)
    if not match:
        return {}, "invalid" if text.lstrip().startswith("---") else "absent"
    fields: Dict[str, Any] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        key = key.strip().strip("\"'")
        if not separator or key not in _FIELDS:
            continue
        if key in fields:
            return {}, "ambiguous"
        value = value.strip()
        if key == "style_source":
            # 未知来源原字符串可能含敏感信息，不回显。
            fields[key] = "owner_inbound_v1" if value == "owner_inbound_v1" else "unknown"
        elif key in {"style_enabled", "manual_style_enabled", "allow_emoji_only", "preserve_trailing_period"}:
            if value not in {"true", "false"}:
                return {}, "invalid"
            fields[key] = value == "true"
        else:
            try:
                number = float(value)
            except ValueError:
                return {}, "invalid"
            if not math.isfinite(number) or not 0 <= number <= 100000000:
                return {}, "invalid"
            fields[key] = number
    return fields, "ok"


def _profiles() -> Dict[str, Any]:
    names, status, limited = _entries(_DATA / "chats")
    groups = [name for name in names if _GROUP.fullmatch(name)]
    result = []
    for name in groups[:_MAX_GROUPS]:
        metadata, text = _read(_DATA / "chats" / name / "SKILL.md")
        fields, parse_status = _frontmatter(text) if text is not None else ({}, "unavailable")
        ownership = "未知 / 待人工核实"
        if parse_status == "ok":
            if "manual_style_enabled" in fields:
                ownership = "人工管理（包括人工关闭；不由自动刷新接管）"
            elif fields.get("style_source") == "owner_inbound_v1":
                ownership = "自动生成：本账号入站 / 操作员声明语料"
        result.append({"group": _alias(name), "file": metadata, "parse_status": parse_status,
                       "ownership": ownership, "fields": fields})
    corpus, _ = _read(_DATA / "style_corpus/owner_verified.jsonl")
    return {"status": status, "limited": limited or len(groups) > _MAX_GROUPS, "groups": result,
            "corpus": corpus,
            "source_note": "owner_verified.jsonl 的 source=operator_attested_owner 仅为操作员声明，并非独立真人认证。生成器还读取本账号入站，排除自动出站；本页面不读取账号身份，不重新认证样本。",
            "refresh_note": "修改时间是文件 mtime，不等于最近自动刷新成功时间；未读取到独立刷新日志或当前任务状态。"}


def _artifacts() -> List[Dict[str, Any]]:
    result = []
    for name in ("SOUL.md", "SKILL.md", "self_improvement_state.json"):
        metadata, text = _read(_DATA / name)
        item: Dict[str, Any] = {"name": name, "file": metadata}
        if text is not None and name.endswith(".md"):
            # 仅展示已知规则/标题，不把聊天引文、身份、密钥或不明自由文本下发。
            item["structure"] = {"lines": len(text.splitlines()),
                                 "sections": sum(bool(re.match(r"^#{1,6}\s", line)) for line in text.splitlines())}
            safe_lines = []
            for line in text.splitlines():
                stripped = line.strip()
                if stripped in {"# SOUL", "# SKILL", "## 统计", "## ⚠️ 应避免的表达", "## 被怀疑的场景记录", "## 禁用表达", "## 人工规则"}:
                    safe_lines.append(stripped)
                elif re.fullmatch(r"- (累计发言|有人接话|无人理会|被怀疑是机器人)：[0-9]+(?:（[0-9.]+%）)?", stripped):
                    safe_lines.append(stripped)
            item["preview"] = "\n".join(safe_lines[:80])
            item["preview_note"] = "安全结构预览；聊天引文、身份信息及未知自由文本不下发，不代表完整原文。"
        elif text is not None:
            try:
                state = json.loads(text)
                if not isinstance(state, dict):
                    raise ValueError("shape")
                item["counters"] = {key: value for key in ("total_messages", "got_reply", "ignored", "suspected")
                                    if type(value := state.get(key)) is int and 0 <= value <= 100000000}
            except (ValueError, json.JSONDecodeError, RecursionError, OverflowError):
                item["file"] = {**metadata, "status": "invalid", "message": "状态文件结构损坏"}
        result.append(item)
    return result


def _events() -> Dict[str, Any]:
    names, status, limited = _entries(_DATA / "transcripts")
    files = [name for name in names if _TRANSCRIPT.fullmatch(name) and name != "chat___usage__.jsonl"]
    events = []
    invalid_lines = 0
    tail_only = False
    unreadable = 0
    # 每次最多 32 个文件，每个仅 128 KiB 尾部；不扫描全部聊天历史。
    for name in files[:32]:
        metadata, text = _read(_DATA / "transcripts" / name, tail=True)
        tail_only = tail_only or metadata.get("tail_only", False)
        if text is None:
            unreadable += 1
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("shape")
            except (ValueError, json.JSONDecodeError, RecursionError, OverflowError):
                invalid_lines += 1
                continue
            chat = row.get("chat_id")
            event = row.get("event")
            if (row.get("direction") != "event" or not isinstance(chat, str)
                    or not _GROUP.fullmatch(chat) or not isinstance(event, str) or event not in _EVENTS):
                continue
            timestamp = row.get("ts")
            try:
                when = datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else None
                if when is None or when.tzinfo is None:
                    raise ValueError("time")
                timestamp = when.astimezone(timezone.utc).isoformat()
            except (ValueError, OverflowError):
                invalid_lines += 1
                continue
            # detail 常含候选正文、命中词和成员 ID；绝不返回。
            events.append({"group": _alias(chat), "event": event, "label": _EVENTS[event], "ts": timestamp})
    events.sort(key=lambda event: event["ts"], reverse=True)
    return {"status": status, "events": events[:100], "limited": limited or len(files) > 32 or len(events) > 100,
            "tail_only": tail_only, "invalid_lines": invalid_lines, "unreadable_files": unreadable,
            "coverage": "最多 32 个日志文件各 128 KiB 尾部、显示最近 100 条已知群级事件。不是全群总数、实时状态或有效静默剩余时间；未落盘的重复/低信息/分片拦截无法证明。"}


@router.get("")
def snapshot(response: Response) -> Dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(), "runtime": "unknown",
        "runtime_note": "仅读取落盘产物，非实时进程状态；不证明插件已加载、账号已连接或功能已生效。",
        "profiles": _profiles(), "artifacts": _artifacts(), "guards": _events(),
        "lab": {
            "url": "https://example.com/",
            "evidence": "独立实验室应用的外链信息（部署地址由使用者自行配置）。",
            "auth_note": "实验室使用独立认证，不复用管理面板、Telegram session 或密码。",
            "isolation_note": "独立实验室应用；仅提供外链，不嵌入、不迁移、不代理其导入/消息/重置操作。进入后操作属于实验室，非本页只读操作。",
        },
    }
