"""合成不完整旧状态快照；真实应用入口不得执行修改。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from src.A_memorix.core.runtime.services import feedback_correction_service as module

@pytest.mark.parametrize('snapshot',[None,{}, {'old':None},{'old':{}}, {'other':{'is_inactive':False}}])
def test_missing_old_snapshot_blocks_mutation(monkeypatch,snapshot):
    monkeypatch.setattr(module,'feedback_cfg_auto_apply_threshold',lambda:0.8)
    store=Mock()
    store.get_relation_status_batch.return_value=snapshot
    forget=Mock(return_value={'success':False})
    ingest=AsyncMock()
    service=SimpleNamespace(metadata_store=store,
        _resolve_feedback_relation_hashes=Mock(return_value=['old']),
        _query_relation_rows_by_hashes=Mock(return_value=[]),
        _apply_v5_relation_action=forget,_ingest_feedback_relations=ingest)
    with pytest.raises(ValueError,match='incomplete_feedback_relation_snapshots'):
        asyncio.run(module.MemoryFeedbackCorrectionService._apply_feedback_decision(service,
            task_id=1,query_tool_id='synthetic',session_id='synthetic',hit_map={},
            decision={'decision':'reject','confidence':1,'target_hashes':['old']}))
    forget.assert_not_called()
    ingest.assert_not_awaited()
    store.append_feedback_action_log.assert_not_called()
