"""合成快照读取故障，验证真实应用入口在修改之前退出。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from src.A_memorix.core.runtime.services import feedback_correction_service as module


@pytest.mark.parametrize('failure_stage',['snapshot','hash'])
def test_new_relation_snapshot_failure_precedes_mutation(monkeypatch,failure_stage):
    monkeypatch.setattr(module,'feedback_cfg_auto_apply_threshold',lambda:0.8)
    error=OSError('synthetic snapshot failure')
    store=Mock()
    store.compute_relation_hash.return_value='new'
    if failure_stage=='hash':
        store.compute_relation_hash.side_effect=error
    def statuses(hashes):
        if hashes==['new']:
            raise error
        return {'old':{'is_inactive':False}}
    store.get_relation_status_batch.side_effect=statuses
    forget=Mock(return_value={'success':True})
    ingest=AsyncMock()
    service=SimpleNamespace(metadata_store=store,
        _resolve_feedback_relation_hashes=Mock(return_value=['old']),
        _query_relation_rows_by_hashes=Mock(return_value=[]),
        _apply_v5_relation_action=forget,_ingest_feedback_relations=ingest)
    with pytest.raises(OSError) as caught:
        asyncio.run(module.MemoryFeedbackCorrectionService._apply_feedback_decision(service,
            task_id=1,query_tool_id='synthetic',session_id='synthetic',hit_map={},
            decision={'decision':'correct','confidence':1,'target_hashes':['old'],
                'corrected_relations':[{'subject':'甲','predicate':'喜欢','object':'乙','confidence':1}]}))
    assert caught.value is error
    forget.assert_not_called()
    ingest.assert_not_awaited()
    store.append_feedback_action_log.assert_not_called()
