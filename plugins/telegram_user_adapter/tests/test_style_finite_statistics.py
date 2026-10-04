"""无效同群统计不得进入提示，也不应抹掉独立人工限制。"""
import pytest
from src.chat.utils import scene_context as module


@pytest.mark.parametrize('value', ['inf', '-inf', 'nan', '-1', 'invalid'])
def test_invalid_peer_median_preserves_manual_constraints(tmp_path, monkeypatch, value):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, '_style_cache', {})
    monkeypatch.setattr(module, '_style_cache_at', 0.0)
    path = tmp_path / 'data/plugins/adapter/chats/-1/SKILL.md'
    path.parent.mkdir(parents=True)
    path.write_text('---\nstyle_enabled: true\nstyle_max_chars: 80\nmax_chars: 150\nmax_emoji: 0\npeer_style_samples: 100\npeer_median_chars: ' + value + '\npeer_question_rate: 0.5\nmanual_style_enabled: true\n---\nKEEP_MANUAL\n', encoding='utf-8')
    text = module._load_chat_style('-1')
    assert 'KEEP_MANUAL' in text and '150 字符' in text
    assert '不使用 emoji' in text
    assert '中位长度' not in text
    assert '本群存在自然追问' not in text
