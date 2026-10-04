"""表达解析异常日志不得泄露模型正文或异常参数。"""
from unittest.mock import Mock
from src.chat.replyer import maisaka_expression_selector as module


def test_parse_failure_logs_type_not_private_response(monkeypatch):
    log = Mock()
    monkeypatch.setattr(module, 'logger', log)
    monkeypatch.setattr(module, 'repair_json', Mock(side_effect=ValueError('PRIVATE_EXCEPTION')))
    selector = module.MaisakaExpressionSelector()
    assert selector._parse_selected_ids('PRIVATE_MODEL_RESPONSE', []) == []
    log.warning.assert_called_once()
    rendered = str(log.mock_calls)
    assert 'ValueError' in rendered
    assert 'PRIVATE_MODEL_RESPONSE' not in rendered
    assert 'PRIVATE_EXCEPTION' not in rendered
    assert not log.warning.call_args.kwargs.get('exc_info')
