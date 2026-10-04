"""真实规范化→应用入口；异常评分不得被夹成满分。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.A_memorix.core.runtime.services import feedback_correction_service as module

@pytest.mark.parametrize('value',[float('inf'),float('-inf'),float('nan'),1.1,-0.1,True,False,'inf','bad',[],{},None])
def test_invalid_normalized_decision_cannot_apply(monkeypatch,value):
    cls=module.MemoryFeedbackCorrectionService
    decision=cls._normalize_feedback_decision({'decision':'reject','confidence':value,'target_hashes':['synthetic']},hit_hashes=['synthetic'])
    assert decision['decision']=='none'
    assert decision['confidence']==0.0
    monkeypatch.setattr(module,'feedback_cfg_auto_apply_threshold',lambda:0.0)
    resolve=Mock(side_effect=AssertionError('must not reach targets'))
    result=asyncio.run(cls._apply_feedback_decision(SimpleNamespace(_resolve_feedback_relation_hashes=resolve),task_id=1,query_tool_id='synthetic',session_id='synthetic',decision=decision,hit_map={}))
    assert result['applied'] is False
    resolve.assert_not_called()

@pytest.mark.parametrize('value',[0,0.8,1,'0.8'])
def test_valid_normalized_confidence_preserved(value):
    result=module.MemoryFeedbackCorrectionService._normalize_feedback_decision({'decision':'reject','confidence':value},hit_hashes=[])
    assert result['decision']=='reject'
    assert result['confidence']==float(value)
