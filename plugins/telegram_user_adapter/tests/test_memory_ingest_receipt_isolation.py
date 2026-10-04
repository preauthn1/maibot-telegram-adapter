"""合成底层回执的对象隔离；真实适配器，不调用存储。"""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.A_memorix.core.runtime.services.feedback_correction_service import MemoryFeedbackCorrectionService as Service

@pytest.mark.parametrize('status',[True,False,'false'])
def test_receipt_not_mutated_or_shared(status):
    payload={'success':status,'stored_ids':['synthetic-paragraph','synthetic-relation'],
             'warnings':['synthetic-warning'],'metadata':{'branches':['synthetic']}}
    before=deepcopy(payload)
    service=SimpleNamespace(ingest_text=AsyncMock(return_value=payload),_chat_source=lambda s:'synthetic:'+s)
    result=asyncio.run(Service._ingest_feedback_relations(service,query_tool_id='synthetic',session_id='synthetic',relation_hashes=['old'],corrected_relations=[{'subject':'甲','predicate':'喜欢','object':'乙','confidence':1}]))
    assert payload==before
    assert result is not payload
    result['metadata']['branches'].append('consumer-change')
    result['warnings'].append('consumer-warning')
    result['stored_ids'].append('consumer-id')
    assert payload==before
