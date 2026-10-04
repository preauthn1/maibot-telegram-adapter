"""真实工具入口的首次时间检索路由；检索服务替身不访问生产。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.maisaka.builtin_tool import query_memory as module
from src.maisaka.builtin_tool.context import BuiltinToolRuntimeContext
from src.services.memory_service import MemorySearchResult, MemoryHit

@pytest.mark.parametrize('mode,start,end,expected', [
    ('search','2026/01/01',None,'hybrid'),
    ('search',None,'2026/01/31','hybrid'),
    ('search','2026/01/01','2026/01/31','hybrid'),
    ('search',None,None,'search'),
    ('time','2026/01/01',None,'time'),
    ('episode','2026/01/01',None,'episode'),
])
def test_primary_time_mode(monkeypatch,mode,start,end,expected):
    search=AsyncMock(return_value=MemorySearchResult(hits=[MemoryHit(content='合成记忆')]))
    monkeypatch.setattr(module.memory_service,'search',search)
    monkeypatch.setattr(module,'_resolve_person_id',lambda **kw:('',''))
    runtime=SimpleNamespace(session_id='synthetic',log_prefix='synthetic',chat_stream=SimpleNamespace(platform='telegram',user_id='17',group_id='group'))
    ctx=BuiltinToolRuntimeContext(SimpleNamespace(),runtime)
    invocation=SimpleNamespace(tool_name='query_memory',arguments={'query':'合成查询','mode':mode,'time_start':start,'time_end':end})
    result=asyncio.run(module.handle_tool(ctx,invocation))
    assert result.success and search.await_count==1
    assert search.await_args.kwargs['mode']==expected
    assert search.await_args.kwargs['time_start']==start
    assert search.await_args.kwargs['time_end']==end
    assert result.structured_content['mode']==mode
    assert result.structured_content['effective_mode']==expected
    assert result.structured_content['fallback_applied'] is False
