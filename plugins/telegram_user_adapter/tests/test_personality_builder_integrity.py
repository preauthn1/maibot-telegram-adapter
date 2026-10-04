"""执行真实生成器构建方法，检查空配置及异常分支。"""
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.chat.replyer import maisaka_generator_base as module


def test_empty_persona_keeps_factual_boundary(monkeypatch):
    config = SimpleNamespace(bot=SimpleNamespace(nickname='测试角色', alias_names=[]),
        personality=SimpleNamespace(personality='', enable_identity_guard=True),
        experimental=SimpleNamespace(emotion_trait=None))
    monkeypatch.setattr(module, 'global_config', config)
    monkeypatch.setattr(module, 'build_personality_emotion_suffix', lambda _: '')
    monkeypatch.setattr(module, 'build_scoped_experience_prompt_block', lambda _: '')
    generator = object.__new__(module.BaseMaisakaReplyGenerator)
    generator.chat_stream = None
    prompt = generator._build_personality_prompt()
    assert '自动助手' in prompt
    assert '一个真实的人' not in prompt
    assert '是人类。' not in prompt
    assert '角色与事实边界' in prompt
    assert '休息、放松、喝水等也算建议' in prompt
    assert '若用户明确请求建议，则正常提供' in prompt


def test_broken_configuration_does_not_invent_identity(monkeypatch):
    monkeypatch.setattr(module, 'global_config', None)
    generator = object.__new__(module.BaseMaisakaReplyGenerator)
    prompt = generator._build_personality_prompt()
    assert '配置读取失败' in prompt
    assert '自动助手' in prompt
    assert '是人类。' not in prompt
