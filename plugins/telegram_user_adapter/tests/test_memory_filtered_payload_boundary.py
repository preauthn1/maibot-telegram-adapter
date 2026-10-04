"""合成策略过滤响应不应泄漏残留命中；仅底层调用为替身。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from src.services.memory_service import memory_service
from src.maisaka.builtin_tool import query_memory as tool
from src.maisaka.builtin_tool.context import BuiltinToolRuntimeContext


def test_filtered_response_discards_residual_hits(monkeypatch):
    invoke=AsyncMock(return_value={'success':True,'filtered':True,'summary':'SYNTHETIC_STALE_SUMMARY','hits':[{'content':'SYNTHETIC_STALE_HIT'}]})
    monkeypatch.setattr(memory_service,'_invoke',invoke)
    monkeypatch.setattr(tool,'_resolve_person_id',lambda **kw:('synthetic-person','合成人物'))
    runtime=SimpleNamespace(session_id='synthetic',log_prefix='synthetic',chat_stream=SimpleNamespace(platform='telegram',user_id='17',group_id='group'))
    ctx=BuiltinToolRuntimeContext(SimpleNamespace(),runtime)
    result=asyncio.run(tool.handle_tool(ctx,SimpleNamespace(tool_name='query_memory',arguments={'query':'合成查询'})))
    assert result.success
    assert result.structured_content['filtered'] is True
    assert result.structured_content['hits']==[]
    assert result.structured_content['fallback_applied'] is False
    assert '过滤策略' in result.content
    assert 'SYNTHETIC_STALE' not in str(result)
    assert not result.metadata.get('replyer_memory_reference')
    assert invoke.await_count==1
