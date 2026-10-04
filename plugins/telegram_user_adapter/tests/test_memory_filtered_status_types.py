"""合成过滤标志：不能把字符串false误当策略跳过。"""
import asyncio
from unittest.mock import AsyncMock
import pytest
from src.services.memory_service import memory_service

@pytest.mark.parametrize('value', ['false','true',0,1,None,[],{}])
def test_invalid_filtered_status_fails(monkeypatch,value):
    monkeypatch.setattr(memory_service,'_invoke',AsyncMock(return_value={'success':True,'filtered':value,'hits':[{'content':'合成正文'}]}))
    result=asyncio.run(memory_service.search('合成查询'))
    assert result.success is False
    assert result.filtered is False
    assert not result.hits
    assert '失败' in result.error

@pytest.mark.parametrize('value', [True,False,'absent'])
def test_valid_filtered_status(monkeypatch,value):
    payload={'success':True,'hits':[{'content':'  合成正文\n'}]}
    if value!='absent':
        payload['filtered']=value
    monkeypatch.setattr(memory_service,'_invoke',AsyncMock(return_value=payload))
    result=asyncio.run(memory_service.search('合成查询'))
    assert result.success
    assert result.filtered is (value is True)
    if value is True:
        assert not result.hits
    else:
        assert result.hits[0].content=='  合成正文\n'
