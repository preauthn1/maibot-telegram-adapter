"""聚合关键词子检索必须遵守时间范围；执行边界使用替身。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.A_memorix.core.runtime.models import KernelSearchRequest
from src.A_memorix.core.runtime.services.memory_search_service import MemorySearchService
from src.A_memorix.core.runtime.services.search_hit_processing_service import MemorySearchHitProcessingService

@pytest.mark.parametrize('start,end', [('2026/01/01','2026/01/31'),('2026/01/01',None),(None,'2026/01/31'),(None,None)])
def test_aggregate_search_time_scope(start,end):
    normalize=MemorySearchHitProcessingService._normalize_search_time_window
    request=KernelSearchRequest(query='合成查询',mode='aggregate',time_start=start,time_end=end,chat_id='synthetic')
    execute=AsyncMock(return_value=SimpleNamespace(success=True,results=[],error=''))
    service=SimpleNamespace(_search_execution_for_chat_scope=execute,_build_runtime_config=lambda:{},
        _normalize_search_time_window=normalize,_filter_hits_by_retrieval_scope=lambda hits,scope:hits)
    result=asyncio.run(MemorySearchService._aggregate_search(service,'合成查询',5,request))
    kwargs=execute.await_args.kwargs
    assert execute.await_count==1
    assert kwargs['request'] is request
    if start is not None or end is not None:
        window=normalize(start,end)
        assert kwargs['query_type']=='hybrid'
        assert kwargs['time_from']==window.query_start
        assert kwargs['time_to']==window.query_end
    else:
        assert kwargs['query_type']=='search'
    # aggregate仍使用search作为子结果槽名，与实际执行模式区分。
    assert result['query_type']=='search' and result['success']
