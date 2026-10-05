# SPDX-License-Identifier: GPL-3.0-or-later
# Modified 2026-10-06; see PORT-NOTICES.md for pinned upstream attribution.
"""公开发布：管理员逐内容批准 + 本地所有权日志；不自动创建账号。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import time

from .fidelity.telegraph_nodes import render_nodes, validate_format


_SECRET = re.compile(r"(?i)(-----BEGIN .*PRIVATE KEY|(?:api[_-]?key|api[_-]?hash|token|password|session|string_session|secret)\s*[:=]|bearer\s+[a-z0-9]|sk-[a-z0-9]{16,}|\b[0-9]{6,}:[a-zA-Z0-9_-]{25,}|[a-z0-9_+/=-]{80,})")


def publication_digest(scope: str, action: str, page: str, title: str, text: str, format: str = "plain") -> str:
    validate_format(format)
    # Preserve historical plaintext approvals/intents; never reuse them for Markdown.
    fields = [scope, action, page, title, text]
    if format == "markdown":
        fields = ["telegraph-markdown-v1", format, *fields]
    body = json.dumps(fields, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


class PublicPages:
    def __init__(self, directory: Path, call: Any = None) -> None:
        self.directory = directory
        self.call = call or self._http_call
        self.lock = asyncio.Lock()

    def _db(self) -> sqlite3.Connection:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.directory / "page-ownership.sqlite3"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        db = sqlite3.connect(path, timeout=2)
        db.execute("CREATE TABLE IF NOT EXISTS pages(path TEXT PRIMARY KEY, scope TEXT NOT NULL, title TEXT NOT NULL, updated INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS intents(digest TEXT PRIMARY KEY, state TEXT NOT NULL, path TEXT NOT NULL DEFAULT '')")
        db.commit()
        return db

    def list(self, scope: str) -> dict[str, Any]:
        db = self._db()
        try:
            rows = db.execute("SELECT path,title,updated FROM pages WHERE scope=? ORDER BY updated DESC LIMIT 50", (scope,)).fetchall()
            pages = [{"page": p, "url": "https://telegra.ph/" + p, "title": t, "updated": u} for p,t,u in rows]
            return {"success": True, "pages": pages, "content": json.dumps(pages, ensure_ascii=False)}
        finally:
            db.close()

    async def _http_call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        import aiohttp
        # 固定服务端点，禁止重定向；token 永不记录、回传或作为 URL 查询参数。
        token_file = self.directory / "access-token"
        if token_file.stat().st_mode & 0o077:
            raise ValueError("Telegraph token 文件必须为 0600")
        token = token_file.read_text().strip()
        if not token or len(token) > 512:
            raise ValueError("Telegraph token 无效")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20), trust_env=False) as session:
            async with session.post("https://api.telegra.ph/" + method,
                                    data={**params, "access_token": token}, allow_redirects=False) as response:
                raw = bytearray()
                async for chunk in response.content.iter_chunked(4096):
                    raw.extend(chunk)
                    if len(raw) > 65536:
                        raise ValueError("Telegraph 响应过大")
                if response.status != 200:
                    raise ValueError("Telegraph 请求失败，结果不确定；禁止自动重试")
                data = json.loads(raw)
                if data.get("ok") is not True or not isinstance(data.get("result"), dict):
                    raise ValueError("Telegraph 未确认操作")
                return data["result"]

    async def publish(self, scope: str, action: str, page: str, title: str, text: str,
                      *, enabled: bool, consent: bool, format: str = "plain") -> dict[str, Any]:
        validate_format(format)
        if enabled is not True or consent is not True:
            raise ValueError("公开且不可删除：必须配置启用、管理员逐内容批准和本次确认")
        if action not in {"create", "edit"}:
            raise ValueError("操作无效")
        if action == "create" and page:
            raise ValueError("创建不得指定页面")
        if action == "edit" and not re.fullmatch(r"[A-Za-z0-9_%.-]{1,256}", page):
            raise ValueError("只接受本地日志中的精确页面路径")
        if not isinstance(title, str) or not 1 <= len(title) <= 128 or not isinstance(text, str) or not text.strip():
            raise ValueError("标题或正文无效")
        if len(text.encode()) > 32000 or _SECRET.search(title + "\n" + text):
            raise ValueError("内容过长或包含凭据特征，禁止公开")
        nodes = json.dumps(render_nodes(text, format), ensure_ascii=False)
        digest = publication_digest(scope, action, page, title, text, format)
        approvals_path = self.directory / "approved-publications.json"
        if approvals_path.stat().st_size > 65536:
            raise ValueError("批准文件过大")
        approvals = json.loads(approvals_path.read_text())
        if digest not in approvals:
            raise ValueError("管理员尚未批准该会话的精确公开内容")
        async with self.lock:
            db = self._db()
            try:
                if action == "edit" and not db.execute("SELECT 1 FROM pages WHERE path=? AND scope=?", (page, scope)).fetchone():
                    raise ValueError("页面不属于当前会话")
                existing = db.execute("SELECT state,path FROM intents WHERE digest=?", (digest,)).fetchone()
                if existing:
                    if existing[0] == "done":
                        return {"success": True, "published": True, "reused": True, "page": existing[1], "url": "https://telegra.ph/" + existing[1]}
                    raise ValueError("此前发布状态不确定，须人工核对；禁止自动重试")
                # 在外部操作前持久化 intent；崩溃后 fail closed，不重复公开。
                db.execute("INSERT INTO intents(digest,state) VALUES (?, 'pending')", (digest,))
                db.commit()
                method = "createPage" if action == "create" else "editPage/" + page
                result = await self.call(method, {"title": title, "content": nodes, "return_content": "false"})
                path = result.get("path", "")
                if not isinstance(path, str) or not re.fullmatch(r"[A-Za-z0-9_%.-]{1,256}", path) or (page and path != page):
                    raise ValueError("服务端页面标识无效；需人工核对")
                # 外部写入后读回精确页面，核对正文；失败保留 pending。
                check = await self.call("getPage/" + path, {"return_content": "true"})
                if check.get("title") != title or check.get("content") != json.loads(nodes):
                    raise ValueError("公开页面回读不一致；需人工核对")
                owner = db.execute("SELECT scope FROM pages WHERE path=?", (path,)).fetchone()
                if owner and owner[0] != scope:
                    raise ValueError("所有权冲突")
                db.execute("INSERT OR REPLACE INTO pages VALUES (?,?,?,?)", (path, scope, title, int(time.time())))
                db.execute("UPDATE intents SET state='done',path=? WHERE digest=?", (path,digest))
                db.commit()
                return {"success": True, "published": True, "page": path, "url": "https://telegra.ph/" + path}
            finally:
                db.close()
