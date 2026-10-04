"""合成纠正列表损坏或超限时，禁止部分自动应用。"""
import pytest
from src.A_memorix.core.runtime.services.feedback_correction_service import MemoryFeedbackCorrectionService as Service

GOOD={'subject':'合成甲','predicate':'喜欢','object':'合成乙','confidence':0.8}

@pytest.mark.parametrize('bad',[None,'broken',{}, {'subject':'甲','predicate':'','object':'乙'}, {'subject':['甲'],'predicate':'喜欢','object':'乙'}, {'subject':'甲','predicate':'喜欢','object':True}])
def test_mixed_bad_relation_disables_correction(bad):
    result=Service._normalize_feedback_decision({'decision':'correct','confidence':1,'corrected_relations':[GOOD,bad]},hit_hashes=[])
    assert result['decision']=='none'
    assert result['corrected_relations']==[]

def test_over_limit_not_silently_truncated():
    result=Service._normalize_feedback_decision({'decision':'correct','confidence':1,'corrected_relations':[dict(GOOD,object=str(i)) for i in range(7)]},hit_hashes=[])
    assert result['decision']=='none'
    assert result['corrected_relations']==[]

def test_six_valid_relations_preserved():
    rows=[dict(GOOD,object=str(i)) for i in range(6)]
    result=Service._normalize_feedback_decision({'decision':'correct','confidence':1,'corrected_relations':rows},hit_hashes=[])
    assert result['decision']=='correct'
    assert result['corrected_relations']==rows
