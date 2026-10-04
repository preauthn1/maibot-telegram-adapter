"""合成写入回执：显式状态必须布尔；缺省兼容内部ingest协议。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.A_memorix.core.runtime.services.feedback_correction_service import MemoryFeedbackCorrectionService as Service

@pytest.mark.parametrize('status,expected', [('false',False),('true',False),(1,False),(0,False),(None,False),([],False),({},False),(True,True),(False,False)])
def test_explicit_receipt_status(status,expected):
    payload={'success':status,'stored_ids':['synthetic-paragraph','synthetic-relation']}
    service=SimpleNamespace(ingest_text=AsyncMock(return_value=payload),_chat_source=lambda s:'synthetic:'+s)
    result=asyncio.run(Service._ingest_feedback_relations(service,query_tool_id='synthetic',session_id='synthetic',relation_hashes=['old'],corrected_relations=[{'subject':'甲','predicate':'喜欢','object':'乙','confidence':1}]))
    assert result['success'] is expected
    if type(status) is not bool:
        assert result['error']=='invalid_ingest_success_type'

def test_missing_status_remains_compatible():
    service=SimpleNamespace(ingest_text=AsyncMock(return_value={'stored_ids':['synthetic-paragraph','synthetic-relation']}),_chat_source=lambda s:'synthetic:'+s)
    result=asyncio.run(Service._ingest_feedback_relations(service,query_tool_id='synthetic',session_id='synthetic',relation_hashes=['old'],corrected_relations=[{'subject':'甲','predicate':'喜欢','object':'乙','confidence':1}]))
    assert result['success'] is True
