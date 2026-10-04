"""真实自动应用入口的写入前门槛；不调用模型、不写生产存储。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.A_memorix.core.runtime.services import feedback_correction_service as module

@pytest.mark.parametrize('decision,targets,reason', [
    ({'decision':'correct','confidence':0.2},['synthetic-relation'],'low_confidence'),
    ({'decision':'none','confidence':1.0},['synthetic-relation'],'decision_none_no_auto_apply'),
    ({'decision':'correct','confidence':1.0},[],'no_relation_targets'),
    ({'decision':'correct','confidence':1.0,'corrected_relations':[]},['synthetic-relation'],'missing_corrected_relations'),
])
def test_incomplete_decision_never_forgets(monkeypatch,decision,targets,reason):
    monkeypatch.setattr(module,'feedback_cfg_auto_apply_threshold',lambda:0.8)
    resolve=Mock(return_value=targets)
    read=Mock(side_effect=AssertionError('unexpected storage access'))
    forget=Mock(side_effect=AssertionError('unexpected mutation'))
    service=SimpleNamespace(metadata_store=Mock(),_resolve_feedback_relation_hashes=resolve,
        _query_relation_rows_by_hashes=read,_apply_v5_relation_action=forget)
    result=asyncio.run(module.MemoryFeedbackCorrectionService._apply_feedback_decision(
        service,task_id=1,query_tool_id='synthetic',session_id='synthetic',decision=decision,hit_map={}))
    assert result['applied'] is False and result['reason']==reason
    read.assert_not_called()
    forget.assert_not_called()
    assert service.metadata_store.mock_calls==[]
    assert resolve.call_count==(0 if reason in ('low_confidence','decision_none_no_auto_apply') else 1)
