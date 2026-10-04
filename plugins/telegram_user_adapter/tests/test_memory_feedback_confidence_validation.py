"""合成异常置信度不得到达关系修改入口。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.A_memorix.core.runtime.services import feedback_correction_service as module

@pytest.mark.parametrize('confidence', [float('nan'),float('inf'),float('-inf'),1.1,-0.1,True,False,'nan','inf','bad',[],{}])
def test_invalid_confidence_stops_before_storage(monkeypatch,confidence):
    monkeypatch.setattr(module,'feedback_cfg_auto_apply_threshold',lambda:0.8)
    resolve=Mock(return_value=[])
    store=Mock()
    service=SimpleNamespace(metadata_store=store,_resolve_feedback_relation_hashes=resolve)
    result=asyncio.run(module.MemoryFeedbackCorrectionService._apply_feedback_decision(service,
        task_id=1,query_tool_id='synthetic',session_id='synthetic',
        decision={'decision':'reject','confidence':confidence,'target_hashes':['synthetic']},hit_map={}))
    assert result['applied'] is False and result['reason']=='invalid_confidence'
    resolve.assert_not_called()
    assert store.mock_calls==[]
