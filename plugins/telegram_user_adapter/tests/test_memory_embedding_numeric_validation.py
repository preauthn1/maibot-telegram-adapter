"""编码返回值校验；合成embedding/索引，不调用外部模型。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import numpy as np
import pytest
from src.A_memorix.core.runtime.services.vector_runtime_service import MemoryVectorRuntimeService as Service

@pytest.mark.parametrize('value',[[[float('nan'),1]],[[float('inf'),1]],[[float('-inf'),1]],[[[1,2]]],[[]]])
def test_invalid_embedding_never_reaches_index(value):
    class Index:
        add=Mock()
        def __contains__(self,key):return True
    index=Index()
    svc=SimpleNamespace(vector_store=index,embedding_manager=SimpleNamespace(encode_batch=AsyncMock(return_value=value)))
    result=asyncio.run(Service._encode_and_add_rebuild_vectors(svc,items=[('synthetic','合成正文')],batch_size=1))
    index.add.assert_not_called()
    assert result==(0,1,'vector_rebuild_failed:ValueError',[],['synthetic'])
