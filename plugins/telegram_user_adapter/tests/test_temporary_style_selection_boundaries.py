"""真实备用风格选择器的确定性边界；不访问生产配置或模型。"""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.chat.replyer import maisaka_generator_base as module


@pytest.mark.parametrize('styles,probability,draw,expected', [
    ([' ', '\t'], 1.0, 0.0, ''),
    ([' 简洁 ', ' 温和 '], 0.0, 0.0, ''),
    ([' 简洁 ', ' 温和 '], 0.5, 0.9, ''),
    ([' ', ' 简洁 ', ' 温和 '], 1.0, 0.9, '温和'),
])
def test_real_temporary_style_selection(monkeypatch, styles, probability, draw, expected):
    config = SimpleNamespace(personality=SimpleNamespace(
        multiple_reply_style=styles, multiple_probability=probability))
    monkeypatch.setattr(module, 'global_config', config)
    random_draw = Mock(return_value=draw)
    choose = Mock(side_effect=lambda candidates: candidates[-1])
    monkeypatch.setattr(module.random, 'random', random_draw)
    monkeypatch.setattr(module.random, 'choice', choose)
    result = module.BaseMaisakaReplyGenerator._select_temporary_reply_style()
    assert result == expected
    if expected:
        choose.assert_called_once_with(['简洁', '温和'])
    else:
        choose.assert_not_called()
    if not any(s.strip() for s in styles) or probability <= 0:
        random_draw.assert_not_called()
    else:
        random_draw.assert_called_once_with()
    assert config.personality.multiple_reply_style == styles
