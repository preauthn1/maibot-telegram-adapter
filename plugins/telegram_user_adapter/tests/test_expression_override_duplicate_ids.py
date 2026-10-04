"""选择后对象覆盖排除冲突编号，同时保留无编号临时表达。"""
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector


def test_override_conflicting_ids_are_excluded_without_losing_anonymous_style():
    rows = [
        {'id':2, 'situation':'倾诉', 'style':'先回应感受'},
        {'id':2, 'situation':'倾诉', 'style':'立即给出建议'},
        {'id':3, 'situation':'核实', 'style':'保留事实归属'},
        {'situation':'倾诉', 'style':'不急着解决问题'},
    ]
    normalized = MaisakaExpressionSelector._normalize_selected_expressions(rows)
    assert [r.get('id') for r in normalized] == [3, None]
    assert normalized[-1]['style'] == '不急着解决问题'
    assert len(rows) == 4


def test_invalid_duplicate_still_invalidates_ambiguous_id():
    rows = [{'id':2,'situation':'倾诉','style':'回应感受'}, {'id':2,'style':''}]
    assert MaisakaExpressionSelector._normalize_selected_expressions(rows) == []
