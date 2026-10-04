"""辅助选择失败时，不注入未经选择的候选或更新使用时间。"""
import asyncio
from unittest.mock import AsyncMock, Mock
from src.chat.replyer import maisaka_expression_selector as module


def test_missing_runner_skips_unselected_candidates(monkeypatch):
    selector = object.__new__(module.MaisakaExpressionSelector)
    update = Mock()
    monkeypatch.setattr(selector, '_update_last_active_time', update)
    result = asyncio.run(selector._build_default_selection_result(
        session_id='synthetic',
        candidates=[{'id': 1, 'situation': '庆祝', 'style': '热烈祝贺'}],
        target_message='今天被拒了，不想听建议', sub_agent_runner=None))
    assert result.selected_expression_ids == []
    assert result.selected_expressions == []
    assert result.expression_habits == ''
    update.assert_not_called()


def test_runner_failure_skips_style_injection(monkeypatch):
    selector = object.__new__(module.MaisakaExpressionSelector)
    update = Mock()
    monkeypatch.setattr(selector, '_update_last_active_time', update)
    warning = Mock()
    monkeypatch.setattr(module.logger, 'warning', warning)
    result = asyncio.run(selector._build_default_selection_result(
        session_id='synthetic',
        candidates=[{'id':1, 'situation':'庆祝', 'style':'热烈祝贺'}],
        target_message='今天被拒了，不想听建议',
        sub_agent_runner=AsyncMock(side_effect=TimeoutError('PRIVATE_SENTINEL'))))
    assert result.selected_expression_ids == []
    assert result.selected_expressions == []
    assert result.expression_habits == ''
    update.assert_not_called()
    warning.assert_called_once()
    assert 'PRIVATE_SENTINEL' not in str(warning.call_args)
