"""后端状态字段合成边界，不把非空字符串当成功。"""
import asyncio
from unittest.mock import AsyncMock
import pytest
from src.services.memory_service import memory_service

@pytest.mark.parametrize('status', ['false','true',1,0,[],{},None])
def test_explicit_non_boolean_status_fails_closed(monkeypatch,status):
    payload={'success':status,'summary':'PRIVATE_DIAGNOSTIC','hits':[{'content':'PRIVATE_DIAGNOSTIC'}]}
    monkeypatch.setattr(memory_service,'_invoke',AsyncMock(return_value=payload))
    result=asyncio.run(memory_service.search('合成查询'))
    assert result.success is False
    assert not result.hits and not result.summary
    assert 'PRIVATE_DIAGNOSTIC' not in str(result)

@pytest.mark.parametrize('status', [True,False,'absent'])
def test_valid_status_and_legacy_absence(monkeypatch,status):
    payload={'hits':[{'content':'合成合法正文'}]}
    if status!='absent':
        payload['success']=status
    monkeypatch.setattr(memory_service,'_invoke',AsyncMock(return_value=payload))
    result=asyncio.run(memory_service.search('合成查询'))
    assert result.success is (status is not False)
    assert bool(result.hits) is (status is not False)
