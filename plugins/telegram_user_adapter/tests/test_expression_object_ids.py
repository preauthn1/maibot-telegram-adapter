"""Hook 表达对象中的布尔 ID 不得更新数据库编号。"""
from unittest.mock import Mock
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector


def test_expression_object_bool_id_not_persisted(monkeypatch):
    selector = object.__new__(MaisakaExpressionSelector)
    update = Mock()
    monkeypatch.setattr(selector, '_update_last_active_time', update)
    expressions = selector._normalize_selected_expressions([
        {'id': True, 'situation': '倾诉', 'style': '简短共情'}])
    assert len(expressions) == 1
    assert 'id' not in expressions[0]
    result = selector._build_selection_result_from_expressions(expressions)
    assert result.selected_expression_ids == []
    update.assert_not_called()


def test_integer_expression_id_still_persisted(monkeypatch):
    selector = object.__new__(MaisakaExpressionSelector)
    update = Mock()
    monkeypatch.setattr(selector, '_update_last_active_time', update)
    expressions = selector._normalize_selected_expressions([
        {'id': 2, 'situation': '倾诉', 'style': '简短共情'}])
    result = selector._build_selection_result_from_expressions(expressions)
    assert result.selected_expression_ids == [2]
    update.assert_called_once_with([2])
