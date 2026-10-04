"""合成目标范围：混合越界目标不应被静默缩成部分修改。"""
import pytest
from src.A_memorix.core.runtime.services.feedback_correction_service import MemoryFeedbackCorrectionService as Service

@pytest.mark.parametrize('bad',['unknown',None,1,{},''])
def test_mixed_invalid_target_disables_action(bad):
    result=Service._normalize_feedback_decision({'decision':'reject','confidence':1,'target_hashes':['known',bad]},hit_hashes=['known'])
    assert result['decision']=='none'
    assert result['target_hashes']==[]

@pytest.mark.parametrize('targets',['known',['known']])
def test_valid_target_preserved(targets):
    result=Service._normalize_feedback_decision({'decision':'reject','confidence':1,'target_hashes':targets},hit_hashes=['known'])
    assert result['decision']=='reject'
    assert result['target_hashes']==['known']
