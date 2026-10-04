"""合成哈希返回异常，真实应用入口必须在修改前终止。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from src.A_memorix.core.runtime.services import feedback_correction_service as module

@pytest.mark.parametrize('value',[None,'','  ',False,1,[],{}])
def test_invalid_hash_stops_before_forget(monkeypatch,value):
    monkeypatch.setattr(module,'feedback_cfg_auto_apply_threshold',lambda:0.8)
    store=Mock()
    store.compute_relation_hash.return_value=value
    store.get_relation_status_batch.return_value={'old':{'is_inactive':False}}
    forget=Mock(return_value={'success':False})
    ingest=AsyncMock()
    service=SimpleNamespace(metadata_store=store,
        _resolve_feedback_relation_hashes=Mock(return_value=['old']),
        _query_relation_rows_by_hashes=Mock(return_value=[]),
        _apply_v5_relation_action=forget,_ingest_feedback_relations=ingest)
    with pytest.raises(ValueError,match='invalid_corrected_relation_hash'):
        asyncio.run(module.MemoryFeedbackCorrectionService._apply_feedback_decision(service,
            task_id=1,query_tool_id='synthetic',session_id='synthetic',hit_map={},
            decision={'decision':'correct','confidence':1,'target_hashes':['old'],
                'corrected_relations':[{'subject':'甲','predicate':'喜欢','object':'乙','confidence':1}]}))
    forget.assert_not_called()
    ingest.assert_not_awaited()
    store.append_feedback_action_log.assert_not_called()
