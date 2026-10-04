"""附属使用记录失败不覆盖有效表达选择，进程级取消仍传播。"""
from unittest.mock import Mock
import pytest
from src.chat.replyer import maisaka_expression_selector as module

@pytest.mark.parametrize('via_objects', [False, True])
def test_usage_failure_preserves_selection(monkeypatch, via_objects):
    selector = object.__new__(module.MaisakaExpressionSelector)
    monkeypatch.setattr(module, 'get_db_session', Mock(side_effect=OSError('PRIVATE_DB_DETAIL')))
    log = Mock()
    monkeypatch.setattr(module, 'logger', log)
    candidates = [{'id':2,'situation':'倾诉','style':'先回应感受，不急着给建议','count':1}]
    if via_objects:
        result = selector._build_selection_result_from_expressions(candidates)
    else:
        result = selector._build_selection_result_from_ids(candidates=candidates, selected_ids=[2])
    assert result.selected_expression_ids == [2]
    assert result.selected_expressions == candidates
    assert '先回应感受' in result.expression_habits
    assert log.warning.call_count == 1
    assert 'PRIVATE_DB_DETAIL' not in str(log.mock_calls)
    assert 'OSError' in str(log.mock_calls)


def test_usage_base_exception_is_not_swallowed(monkeypatch):
    selector = object.__new__(module.MaisakaExpressionSelector)
    monkeypatch.setattr(module, 'get_db_session', Mock(side_effect=KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        selector._update_last_active_time([2])
