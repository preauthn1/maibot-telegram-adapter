"""写入回执结构验证，合成底层返回，不写生产记忆。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.A_memorix.core.runtime.services.feedback_correction_service import MemoryFeedbackCorrectionService as Service

@pytest.mark.parametrize('ids', ['paragraph,relation', {'p':'r'}, ['p',1], ['p',None,'r'], ['p','','r'], ['p','r','r'], ['same','same']])
def test_invalid_stored_ids_are_not_success(ids):
    service=SimpleNamespace(ingest_text=AsyncMock(return_value={'success':True,'stored_ids':ids}),_chat_source=lambda s:'synthetic:'+s)
    result=asyncio.run(Service._ingest_feedback_relations(service,query_tool_id='synthetic',session_id='synthetic',relation_hashes=['old'],corrected_relations=[{'subject':'甲','predicate':'喜欢','object':'乙','confidence':1}]))
    assert result['success'] is False
    assert result['error']=='invalid_ingest_stored_ids'
    assert result.get('corrected_relation_hashes',[])==[]
