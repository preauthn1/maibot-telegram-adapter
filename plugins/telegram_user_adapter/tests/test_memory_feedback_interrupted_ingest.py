"""真实应用编排，存储/写入/恢复替身；验证中断后的补偿调用而非真实恢复。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from src.A_memorix.core.runtime.services import feedback_correction_service as module

@pytest.mark.parametrize('error',[RuntimeError('synthetic failure'),asyncio.CancelledError()])
@pytest.mark.parametrize('restore_failed',[False,True])
def test_interrupted_ingest_restores_before_propagating(monkeypatch,error,restore_failed):
    warning=Mock()
    monkeypatch.setattr(module.logger,'warning',warning)
    monkeypatch.setattr(module,'feedback_cfg_auto_apply_threshold',lambda:0.8)
    before={'old':{'is_inactive':False}}
    after={'old':{'is_inactive':True}}
    store=Mock()
    store.get_relation_status_batch.side_effect=lambda hashes: ({} if hashes==["new"] else (after if service._apply_v5_relation_action.called else before))
    store.compute_relation_hash.return_value='new'
    restore=Mock(return_value={'restored_hashes':[] if restore_failed else ['old'],'failed_hashes':['synthetic-private-hash'] if restore_failed else []})
    service=SimpleNamespace(metadata_store=store,
        _resolve_feedback_relation_hashes=Mock(return_value=['old']),
        _query_relation_rows_by_hashes=Mock(return_value=[]),
        _apply_v5_relation_action=Mock(return_value={'success':True}),
        _ingest_feedback_relations=AsyncMock(side_effect=error),
        _restore_feedback_relations_from_snapshots=restore)
    with pytest.raises(type(error)) as caught:
        asyncio.run(module.MemoryFeedbackCorrectionService._apply_feedback_decision(service,
            task_id=1,query_tool_id='synthetic',session_id='synthetic',hit_map={},
            decision={'decision':'correct','confidence':1,'target_hashes':['old'],
                'corrected_relations':[{'subject':'合成甲','predicate':'喜欢','object':'合成乙','confidence':1}]}))
    assert caught.value is error
    restore.assert_called_once()
    assert restore.call_args.kwargs['snapshots']==before
    assert restore.call_args.kwargs['relation_hashes']==['old']
    assert restore.call_args.kwargs['current_statuses']==after
    if restore_failed:
        warning.assert_called_once()
        assert 'failed_count=1' in str(warning.call_args)
        assert 'synthetic-private-hash' not in str(warning.call_args)
    else:
        warning.assert_not_called()
