"""exists回执的只读核验负控；存储替身，真实SQLite正控见partial_ingest测试。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from src.A_memorix.core.runtime.services.feedback_correction_service import MemoryFeedbackCorrectionService as Service

@pytest.mark.parametrize('fault', ['missing_ref','missing_paragraph','deleted','missing_link','inactive','explicit_failure','valid'])
def test_exists_requires_complete_active_state(fault):
    store=SimpleNamespace(
        get_external_memory_ref=Mock(return_value=None if fault=='missing_ref' else {'paragraph_hash':'p'}),
        get_paragraph=Mock(return_value=None if fault=='missing_paragraph' else {'hash':'p','is_deleted':fault=='deleted'}),
        compute_relation_hash=Mock(return_value='r'),
        get_paragraph_relations=Mock(return_value=[] if fault=='missing_link' else [{'hash':'r'}]),
        get_relation=Mock(return_value=None if fault=='inactive' else {'hash':'r'}))
    receipt={'reason':'exists','stored_ids':[],'skipped_ids':['p']}
    if fault=='explicit_failure':
        receipt['success']=False
    svc=SimpleNamespace(metadata_store=store,ingest_text=AsyncMock(return_value=receipt),_chat_source=lambda s:'synthetic:'+s)
    result=asyncio.run(Service._ingest_feedback_relations(svc,query_tool_id='synthetic',session_id='synthetic',relation_hashes=['old'],corrected_relations=[{'subject':'甲','predicate':'喜欢','object':'乙','confidence':0.5}]))
    assert result['success'] is (fault=='valid')
    assert result['stored_ids']==[]
    assert receipt.get('idempotent_replay') is None
    if fault=='valid':
        assert result['corrected_relation_hashes']==['r']
        store.get_relation.assert_called_once_with('r',include_inactive=False)
    if fault=='explicit_failure':
        store.get_external_memory_ref.assert_not_called()
