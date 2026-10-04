"""合成后端命中结构：损坏不是零命中，服务边界保留失败语义。"""
import asyncio
from unittest.mock import AsyncMock
import pytest
from src.services.memory_service import memory_service

@pytest.mark.parametrize('hits', ['broken', {}, {'content':'合成'}, 0, False, [None], ['broken'], [{'content':'合法合成'}, 42]])
def test_invalid_hits_fail_without_partial_result(monkeypatch,hits):
    monkeypatch.setattr(memory_service,'_invoke',AsyncMock(return_value={'success':True,'hits':hits}))
    result=asyncio.run(memory_service.search('合成查询'))
    assert result.success is False
    assert not result.hits
    assert '失败' in result.error

@pytest.mark.parametrize('payload', [{'hits':[]}, {'hits':None}, {}, {'hits':[{'content':'  合成\n正文\n'}]}])
def test_valid_and_legacy_empty_hits(monkeypatch,payload):
    monkeypatch.setattr(memory_service,'_invoke',AsyncMock(return_value=payload))
    result=asyncio.run(memory_service.search('合成查询'))
    assert result.success
    if payload.get('hits'):
        assert result.hits[0].content=='  合成\n正文\n'
    else:
        assert result.hits==[]
