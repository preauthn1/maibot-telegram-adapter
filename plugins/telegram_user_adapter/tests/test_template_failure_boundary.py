"""模板加载异常不应丢失基础事实边界。"""
from types import SimpleNamespace
from src.chat.replyer import maisaka_generator_base as module


def test_template_failure_retains_boundaries(monkeypatch):
    generator = object.__new__(module.BaseMaisakaReplyGenerator)
    generator.chat_stream = None
    monkeypatch.setattr(module, 'global_config', SimpleNamespace(bot=SimpleNamespace(nickname='合成助手')))
    monkeypatch.setattr(generator, '_resolve_session_id', lambda _: 'synthetic')
    monkeypatch.setattr(generator, '_build_group_chat_attention_block', lambda _: '')
    monkeypatch.setattr(generator, '_build_replyer_output_instruction', lambda: '')
    monkeypatch.setattr(generator, '_build_personality_prompt', lambda: '合成人设')
    monkeypatch.setattr(generator, '_select_reply_style', lambda: '')
    def broken(*args, **kwargs):
        raise OSError('synthetic template failure')
    generator._load_prompt = broken
    result = generator._build_system_prompt(None, '')
    assert '模板加载失败' in result
    assert '角色与事实边界' in result
    assert '若用户明确请求建议，则正常提供' in result
    assert '不要编造' in result
