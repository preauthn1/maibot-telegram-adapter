"""实际查询工具的空结果、策略过滤和取消边界；检索服务为合成替身。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.maisaka.builtin_tool import query_memory as module
from src.maisaka.builtin_tool.context import BuiltinToolRuntimeContext
from src.services.memory_service import MemorySearchResult


def context(monkeypatch, results):
    search = AsyncMock(side_effect=results)
    monkeypatch.setattr(module.memory_service, 'search', search)
    monkeypatch.setattr(module, '_resolve_person_id', lambda **kw: ('synthetic-person', '合成人物'))
    runtime = SimpleNamespace(session_id='synthetic', log_prefix='synthetic', chat_stream=SimpleNamespace(platform='telegram', user_id='17', group_id='group'))
    return search, BuiltinToolRuntimeContext(SimpleNamespace(), runtime), SimpleNamespace(tool_name='query_memory', arguments={'query':'合成查询'})


def test_genuine_empty_fallback_remains_success(monkeypatch):
    search, ctx, invocation = context(monkeypatch, [MemorySearchResult(), MemorySearchResult()])
    result = asyncio.run(module.handle_tool(ctx, invocation))
    assert search.await_count == 2
    assert result.success and not result.error_message
    assert '未找到匹配的长期记忆' in result.content
    assert result.structured_content['hits'] == []
    assert not result.metadata.get('replyer_memory_reference')


def test_filtered_primary_never_falls_back(monkeypatch):
    search, ctx, invocation = context(monkeypatch, [MemorySearchResult(filtered=True)])
    result = asyncio.run(module.handle_tool(ctx, invocation))
    assert search.await_count == 1
    assert result.success and result.structured_content['filtered'] is True
    assert result.structured_content['fallback_applied'] is False
    assert '过滤策略' in result.content
    assert not result.metadata.get('replyer_memory_reference')


@pytest.mark.parametrize('stage', ['primary', 'fallback'])
def test_cancel_propagates_without_retries(monkeypatch, stage):
    results = [asyncio.CancelledError()] if stage == 'primary' else [MemorySearchResult(), asyncio.CancelledError()]
    search, ctx, invocation = context(monkeypatch, results)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(module.handle_tool(ctx, invocation))
    assert search.await_count == (1 if stage == 'primary' else 2)
