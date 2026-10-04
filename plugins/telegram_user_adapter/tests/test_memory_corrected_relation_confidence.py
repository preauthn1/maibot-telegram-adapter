"""合成替代关系评分，防止零分提升及异常输入部分应用。"""
import pytest
from src.A_memorix.core.runtime.services.feedback_correction_service import MemoryFeedbackCorrectionService as Service


def decision(value):
    return Service._normalize_feedback_decision({'decision':'correct','confidence':1.0,'target_hashes':['synthetic'],
        'corrected_relations':[{'subject':'合成甲','predicate':'喜欢','object':'合成乙','confidence':0.9},
        {'subject':'合成甲','predicate':'喜欢','object':'合成丙','confidence':value}]},hit_hashes=['synthetic'])

@pytest.mark.parametrize('value',[0,0.5,1,'0'])
def test_valid_relation_score_preserved(value):
    result=decision(value)
    assert result['decision']=='correct'
    assert result['corrected_relations'][1]['confidence']==float(value)

@pytest.mark.parametrize('value',[None,True,False,'bad',float('nan'),float('inf'),-0.1,1.1,[],{}])
def test_invalid_relation_score_blocks_whole_correction(value):
    result=decision(value)
    assert result['decision']=='none'
    assert result['corrected_relations']==[]
