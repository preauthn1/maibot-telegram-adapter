"""真实批量编排；合成索引模拟静默部分写入与既有ID。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import numpy as np
import pytest
from src.A_memorix.core.runtime.services.vector_runtime_service import MemoryVectorRuntimeService

@pytest.mark.parametrize('complete',[False,True])
def test_add_requires_membership(complete):
    class Index:
        def __init__(self):self.ids={'existing'}
        def add(self,*,vectors,ids):
            if complete:self.ids.update(ids)
            return 0
        def __contains__(self,key):return key in self.ids
    index=Index()
    svc=SimpleNamespace(vector_store=index,embedding_manager=SimpleNamespace(
        encode_batch=AsyncMock(return_value=np.ones((2,4),dtype=np.float32))))
    result=asyncio.run(MemoryVectorRuntimeService._encode_and_add_rebuild_vectors(
        svc,items=[('existing','合成一'),('new','合成二')],batch_size=2,vector_store=index))
    if complete:
        assert result==(2,0,'',['existing','new'],[])
    else:
        assert result[0]==0 and result[1]==2
        assert result[3]==[] and result[4]==['existing','new']
        assert result[2]=='vector_rebuild_failed:RuntimeError'


def test_explicit_empty_pool_is_not_replaced():
    class Index:
        def __init__(self):self.ids=set()
        def __len__(self):return len(self.ids)
        def add(self,*,vectors,ids):self.ids.update(ids)
        def __contains__(self,key):return key in self.ids
    target=Index()
    default=Index()
    default.ids.add('unrelated')
    svc=SimpleNamespace(vector_store=default,embedding_manager=SimpleNamespace(
        encode_batch=AsyncMock(return_value=np.ones((1,4),dtype=np.float32))))
    result=asyncio.run(MemoryVectorRuntimeService._encode_and_add_rebuild_vectors(
        svc,items=[('new','合成目标池')],batch_size=1,vector_store=target))
    assert result[0]==1
    assert target.ids=={'new'}
    assert default.ids=={'unrelated'}
