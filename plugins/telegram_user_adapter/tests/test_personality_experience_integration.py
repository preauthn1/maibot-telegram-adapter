"""真实人设装配与磁盘经验读取的组合测试；不调用模型或平台。"""
from types import SimpleNamespace
from src.chat.replyer import maisaka_generator_base as module
from src.chat.message_receive.chat_manager import BotChatSession
from src.chat.utils import scene_context


def test_real_builder_scopes_and_withdraws_experience(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = SimpleNamespace(
        bot=SimpleNamespace(nickname='测试助手', alias_names=[]),
        personality=SimpleNamespace(personality='', enable_identity_guard=True),
        experimental=SimpleNamespace(emotion_trait=None),
    )
    monkeypatch.setattr(module, 'global_config', config)
    # 仅隔离与本测试无关的情绪和场景资料；经验读取及身份规则使用真实实现。
    monkeypatch.setattr(module, 'build_personality_emotion_suffix', lambda _: '')
    monkeypatch.setattr(scene_context, '_load_account_profile', lambda: {})
    monkeypatch.setattr(scene_context, '_style_cache', {})
    monkeypatch.setattr(scene_context, '_style_cache_at', 0.0)
    root = tmp_path / 'data/plugins/adapter'
    paths = {}
    for chat_id, marker in [('-1', 'EXPERIENCE_ONE'), ('-2', 'EXPERIENCE_TWO')]:
        path = root / 'chats' / chat_id / 'prompt_experience.txt'
        path.parent.mkdir(parents=True)
        path.write_text(marker, encoding='utf-8')
        paths[chat_id] = path
        (path.parent / 'SKILL.md').write_text(
            '---\nstyle_enabled: true\nstyle_max_chars: 80\nmax_chars: 150\n'
            'max_emoji: 0\nmanual_style_enabled: true\n---\nSTYLE_' + chat_id,
            encoding='utf-8')
    (root / 'prompt_experience.txt').write_text('GLOBAL_MIXED', encoding='utf-8')
    generator = object.__new__(module.BaseMaisakaReplyGenerator)
    for chat_id, wanted, unwanted in [('-1', 'EXPERIENCE_ONE', 'EXPERIENCE_TWO'),
                                      ('-2', 'EXPERIENCE_TWO', 'EXPERIENCE_ONE')]:
        generator.chat_stream = BotChatSession(session_id='test' + chat_id, platform='telegram', group_id=chat_id, group_name='合成测试群')
        prompt = generator._build_personality_prompt()
        assert '**群聊**' in prompt
        assert '合成测试群' in prompt
        assert 'STYLE_' + chat_id in prompt
        assert 'STYLE_' + ('-2' if chat_id == '-1' else '-1') not in prompt
        assert '不使用 emoji' in prompt and '150 字符' in prompt
        assert wanted in prompt
        assert unwanted not in prompt
        assert 'GLOBAL_MIXED' not in prompt
        assert '待核实' in prompt
        assert '自动助手' in prompt
        assert '若用户明确请求建议，则正常提供' in prompt
        assert '配置读取失败' not in prompt
    paths['-2'].unlink()
    prompt = generator._build_personality_prompt()
    assert 'EXPERIENCE_' not in prompt and 'GLOBAL_MIXED' not in prompt
    assert '角色与事实边界' in prompt
    generator.chat_stream = BotChatSession(session_id='test-private', platform='telegram', user_id='3', user_nickname='合成用户')
    prompt = generator._build_personality_prompt()
    assert 'STYLE_' not in prompt
    assert '**一对一私聊**' in prompt
    assert '**群聊**' not in prompt and '合成测试群' not in prompt
    assert 'EXPERIENCE_' not in prompt and 'GLOBAL_MIXED' not in prompt
    generator.chat_stream = None
    prompt = generator._build_personality_prompt()
    assert 'EXPERIENCE_' not in prompt and 'GLOBAL_MIXED' not in prompt
    assert '自动助手' in prompt
