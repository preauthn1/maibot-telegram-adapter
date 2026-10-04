"""冲突候选ID不能在模型选择后被字典覆盖。"""
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector


def test_duplicate_candidate_id_is_removed_entirely():
    rows = [
        {'id':1,'situation':'倾诉','style':'先回应感受'},
        {'id':2,'situation':'核实','style':'保留事实归属'},
        {'id':1,'situation':'倾诉','style':'声称自己也亲历过'},
    ]
    result = MaisakaExpressionSelector._normalize_candidate_list(rows, [])
    assert [r['id'] for r in result] == [2]
    assert len(rows) == 3


def test_repeated_identical_id_is_also_unambiguous_by_exclusion():
    row = {'id':1,'situation':'倾诉','style':'先回应感受'}
    assert MaisakaExpressionSelector._normalize_candidate_list([row, dict(row)], []) == []
