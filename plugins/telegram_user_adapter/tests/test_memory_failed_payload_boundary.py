"""真实search服务与工具入口；底层返回合成失败payload。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.maisaka.builtin_tool import query_memory as tool
from src.maisaka.builtin_tool.context import BuiltinToolRuntimeContext

@pytest.mark.parametrize('explicit', [True, False])
def test_failed_payload_not_forwarded(monkeypatch, explicit):
    payload={'error':'SYNTHETIC_PRIVATE_ERROR','summary':'SYNTHETIC_PRIVATE_SUMMARY',
             'hits':[{'content':'SYNTHETIC_PRIVATE_HIT','metadata':{'secret':'SYNTHETIC_PRIVATE_METADATA'}}]}
    if explicit:
        payload['success']=False
    invoke=AsyncMock(return_value=payload)
    monkeypatch.setattr(tool.memory_service,'_invoke',invoke)
    monkeypatch.setattr(tool,'_resolve_person_id',lambda **kw:('',''))
    runtime=SimpleNamespace(session_id='synthetic',log_prefix='synthetic',chat_stream=SimpleNamespace(platform='telegram',user_id='17',group_id='group'))
    result=asyncio.run(tool.handle_tool(BuiltinToolRuntimeContext(SimpleNamespace(),runtime),
        SimpleNamespace(tool_name='query_memory',arguments={'query':'合成查询'})))
    assert result.success is False and '失败' in result.error_message
    assert 'SYNTHETIC_PRIVATE' not in str(result)
    assert result.structured_content['hits']==[]
    assert not result.metadata.get('replyer_memory_reference')
    assert invoke.await_count==1


def test_success_payload_keeps_body(monkeypatch):
    body='  合成正文\n\t条件：不出门\n'
    monkeypatch.setattr(tool.memory_service,'_invoke',AsyncMock(return_value={'success':True,'hits':[{'content':body}]}))
    result=asyncio.run(tool.memory_service.search('合成查询'))
    assert result.success and result.hits[0].content==body
