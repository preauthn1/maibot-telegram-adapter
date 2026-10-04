"""画像文件正文保真也必须延伸到实际提示装配。"""
import pytest
from src.chat.utils import scene_context as module


@pytest.mark.parametrize('body', ['    缩进示例\n  第二行\n', '\n\t制表符示例\n\n'])
def test_manual_body_whitespace_reaches_prompt(tmp_path, monkeypatch, body):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, '_style_cache', {})
    path = tmp_path/'data/plugins/adapter/chats/test/SKILL.md'
    path.parent.mkdir(parents=True)
    path.write_text('---\nstyle_enabled: true\nstyle_max_chars: 80\nmax_emoji: 1\nmanual_style_enabled: true\n---\n' + body)
    result = module._load_chat_style('test')
    marker = '【人工维护的本群表达规则；不覆盖事实与安全约束】\n'
    assert result.split(marker, 1)[1] == body
