"""降级检索失败不伪装空结果成功；后端故障为合成替身。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.maisaka.builtin_tool import query_memory as module
from src.maisaka.builtin_tool.context import BuiltinToolRuntimeContext
from src.services.memory_service import MemorySearchResult

@pytest.mark.parametrize('failure', [MemorySearchResult(success=False,error='PRIVATE_BACKEND_DETAIL'), OSError('PRIVATE_BACKEND_DETAIL')])
def test_fallback_failure_is_not_empty_success(monkeypatch,failure):
    search=AsyncMock(side_effect=[MemorySearchResult(),failure])
    monkeypatch.setattr(module.memory_service,'search',search)
    monkeypatch.setattr(module,'_resolve_person_id',lambda **kw:('synthetic-person','合成人物'))
    runtime=SimpleNamespace(session_id='synthetic',log_prefix='synthetic',chat_stream=SimpleNamespace(platform='telegram',user_id='17',group_id='group'))
    ctx=BuiltinToolRuntimeContext(SimpleNamespace(),runtime)
    invocation=SimpleNamespace(tool_name='query_memory',arguments={'query':'合成查询'})
    result=asyncio.run(module.handle_tool(ctx,invocation))
    assert search.await_count==2
    assert result.success is False
    assert '失败' in result.error_message
    assert 'PRIVATE_BACKEND_DETAIL' not in result.error_message
    assert 'PRIVATE_BACKEND_DETAIL' not in str(result.structured_content)
    assert '未找到匹配的长期记忆' not in result.error_message
    assert not result.metadata.get('replyer_memory_reference')
