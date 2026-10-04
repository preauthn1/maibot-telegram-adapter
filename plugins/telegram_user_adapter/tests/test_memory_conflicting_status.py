"""合成后端矛盾状态：有错误时不信任显式success=true。"""
import asyncio
from unittest.mock import AsyncMock
import pytest
from src.services.memory_service import memory_service

@pytest.mark.parametrize('error', ['SYNTHETIC_PRIVATE_ERROR', 'timeout'])
def test_success_with_error_fails_closed(monkeypatch, error):
    invoke = AsyncMock(return_value={'success':True,'error':error,'summary':'SYNTHETIC_PRIVATE_SUMMARY','hits':[{'content':'SYNTHETIC_PRIVATE_HIT'}]})
    monkeypatch.setattr(memory_service, '_invoke', invoke)
    result = asyncio.run(memory_service.search('合成查询'))
    assert result.success is False
    assert not result.hits and not result.summary
    assert '失败' in result.error
    assert 'SYNTHETIC_PRIVATE' not in str(result)
    assert invoke.await_count == 1

@pytest.mark.parametrize('error', ['', None])
def test_success_with_empty_error_remains_success(monkeypatch, error):
    monkeypatch.setattr(memory_service, '_invoke', AsyncMock(return_value={'success':True,'error':error,'hits':[{'content':'  合成事实\n'}]}))
    result = asyncio.run(memory_service.search('合成查询'))
    assert result.success and result.hits[0].content == '  合成事实\n'
