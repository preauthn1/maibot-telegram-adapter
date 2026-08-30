"""web_search 内置工具测试。

不打真实网络——用桩替换 HTTP 层，只验证参数校验、key 轮换、
错误处理和结果格式化。
"""

from __future__ import annotations

from typing import Any, Dict

import urllib.error

import pytest

from src.maisaka.builtin_tool import web_search
from src.maisaka.builtin_tool.context import BuiltinToolRuntimeContext
from src.core.tooling import ToolInvocation


class _StubCtx(BuiltinToolRuntimeContext):
    """只保留构造结果所需能力的桩。"""

    def __init__(self) -> None:  # noqa: D107 - 测试桩不需要完整初始化
        pass


def _invocation(**args: Any) -> ToolInvocation:
    return ToolInvocation(tool_name="web_search", arguments=args)


@pytest.fixture(autouse=True)
def _reset_key_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个用例前重置模块级 key 缓存，避免互相污染。"""

    monkeypatch.setattr(web_search, "_cached_keys", [])
    monkeypatch.setattr(web_search, "_key_cycle", None)


def test_spec_declares_query_required() -> None:
    """query 必填，否则模型可能发空请求。"""

    spec = web_search.get_tool_spec()
    assert spec.name == "web_search"
    assert "query" in spec.parameters_schema["required"]


@pytest.mark.asyncio
async def test_empty_query_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """空 query 直接拒绝，不浪费额度。"""

    monkeypatch.setattr(web_search, "_load_keys", lambda: ["k1"])
    result = await web_search.handle_tool(_StubCtx(), _invocation(query="  "))
    assert not result.success


@pytest.mark.asyncio
async def test_missing_keys_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    """没配 key 时要明确报错，而不是静默返回空结果。"""

    monkeypatch.setattr(web_search, "_load_keys", lambda: [])
    result = await web_search.handle_tool(_StubCtx(), _invocation(query="test"))
    assert not result.success
    assert "key" in result.error_message.lower()


@pytest.mark.asyncio
async def test_successful_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常返回时要产出格式化文本。"""

    monkeypatch.setattr(web_search, "_load_keys", lambda: ["k1"])
    monkeypatch.setattr(web_search, "_next_key", lambda: "k1")

    def _fake(query: str, api_key: str, max_results: int) -> Dict[str, Any]:
        return {
            "answer": "这是结论",
            "results": [{"title": "标题A", "content": "正文A"}],
        }

    monkeypatch.setattr(web_search, "_do_search", _fake)
    result = await web_search.handle_tool(_StubCtx(), _invocation(query="新名词"))

    assert result.success
    assert "这是结论" in result.content
    assert "标题A" in result.content


@pytest.mark.asyncio
async def test_key_rotation_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """一个 key 失效（401/429）时要自动换下一个，而不是直接失败。"""

    monkeypatch.setattr(web_search, "_load_keys", lambda: ["bad", "good"])
    used: list[str] = []
    keys = iter(["bad", "good"])
    monkeypatch.setattr(web_search, "_next_key", lambda: next(keys))

    def _fake(query: str, api_key: str, max_results: int) -> Dict[str, Any]:
        used.append(api_key)
        if api_key == "bad":
            raise urllib.error.HTTPError("url", 429, "rate limit", {}, None)  # type: ignore[arg-type]
        return {"answer": "成功", "results": []}

    monkeypatch.setattr(web_search, "_do_search", _fake)
    result = await web_search.handle_tool(_StubCtx(), _invocation(query="x"))

    assert result.success
    assert used == ["bad", "good"], "没有正确轮换 key"


@pytest.mark.asyncio
async def test_all_keys_failing_reports_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有 key 都失效时要如实报错，不能假装成功。"""

    monkeypatch.setattr(web_search, "_load_keys", lambda: ["k1", "k2"])
    keys = iter(["k1", "k2"])
    monkeypatch.setattr(web_search, "_next_key", lambda: next(keys))

    def _fake(query: str, api_key: str, max_results: int) -> Dict[str, Any]:
        raise urllib.error.HTTPError("url", 401, "unauthorized", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(web_search, "_do_search", _fake)
    result = await web_search.handle_tool(_StubCtx(), _invocation(query="x"))

    assert not result.success


def test_format_truncates_long_content() -> None:
    """长正文必须截断，否则会挤掉真正的聊天上下文。"""

    data = {"results": [{"title": "T", "content": "很长的内容" * 200}]}
    text = web_search._format_results(data, 3)
    assert len(text) < 400


def test_format_handles_empty_results() -> None:
    """没结果时给一句明确的话，而不是空字符串。"""

    assert web_search._format_results({}, 3) == "没有搜到有效结果。"


def test_max_results_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    """max_results 要被夹到合理区间，防止模型要 100 条。"""

    data = {"results": [{"title": f"T{i}", "content": "c"} for i in range(10)]}
    text = web_search._format_results(data, 3)
    assert text.count("- T") == 3
