"""人物过滤降级不得扩大明确的时间范围；检索后端为合成替身。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.maisaka.builtin_tool import query_memory as module
from src.maisaka.builtin_tool.context import BuiltinToolRuntimeContext
from src.services.memory_service import MemorySearchResult, MemoryHit

@pytest.mark.parametrize('start,end', [('2026/01/01','2026/01/31'), ('2026/01/01',None), (None,'2026/01/31')])
def test_person_fallback_preserves_explicit_time_bounds(monkeypatch,start,end):
    search=AsyncMock(side_effect=[MemorySearchResult(), MemorySearchResult(hits=[MemoryHit(content='合成范围内记忆')])])
    monkeypatch.setattr(module.memory_service,'search',search)
    monkeypatch.setattr(module,'_resolve_person_id',lambda **kw:('synthetic-person','合成人物'))
    runtime=SimpleNamespace(session_id='synthetic-session',log_prefix='synthetic',chat_stream=SimpleNamespace(platform='telegram',user_id='17',group_id='synthetic-group'))
    ctx=BuiltinToolRuntimeContext(SimpleNamespace(),runtime)
    invocation=SimpleNamespace(tool_name='query_memory',arguments={'query':'合成查询','mode':'hybrid','time_start':start,'time_end':end})
    result=asyncio.run(module.handle_tool(ctx,invocation))
    assert result.success and search.await_count==2
    primary,fallback=[call.kwargs for call in search.await_args_list]
    assert primary['person_id']=='synthetic-person' and fallback['person_id']==''
    assert fallback['mode']=='hybrid'
    from src.A_memorix.core.utils.search_execution_service import SearchExecutionService
    ok, temporal, error = SearchExecutionService._build_temporal(
        {}, fallback['mode'], fallback['time_start'], fallback['time_end'], None, None)
    assert ok and not error and temporal is not None
    assert (temporal.time_from is not None)==(start is not None)
    assert (temporal.time_to is not None)==(end is not None)
    assert result.structured_content['effective_mode']=='hybrid'
    for key in ('time_start','time_end','chat_id','user_id','group_id','respect_filter','limit'):
        assert fallback[key]==primary[key]
    assert fallback['time_start']==start and fallback['time_end']==end
    assert result.structured_content['fallback_applied'] is True
    assert '人物定向检索未命中' in result.metadata['replyer_memory_reference']
