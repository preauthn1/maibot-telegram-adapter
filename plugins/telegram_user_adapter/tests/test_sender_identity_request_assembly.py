"""同名账号身份从历史构造延伸至完整请求列表；外部附属信息隔离。"""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from src.chat.replyer import maisaka_generator_base as module
from src.maisaka.reasoning_engine import MaisakaReasoningEngine
from src.common.data_models.message_component_data_model import MessageSequence
from src.llm_models.model_client.openai_client import _convert_messages


import pytest


@pytest.mark.parametrize('corrected', [False, True, 'dual'])
@pytest.mark.parametrize('renamed', [False, True])
@pytest.mark.parametrize('target_uid,expected', [('29','兔子，豆包'), ('17','猫，松子')])
def test_history_and_final_target_share_identity_in_request(monkeypatch, target_uid, expected, renamed, corrected):
    generator = object.__new__(module.BaseMaisakaReplyGenerator)
    monkeypatch.setattr(module, 'is_bot_self', lambda *a: False)
    monkeypatch.setattr(generator, '_build_keyword_reaction_prompt', lambda **kw: '')
    # 执行仓库真实系统模板与身份装配，只使用合成账号配置。
    from functools import partial
    from pathlib import Path
    from src.common.prompt_i18n import load_prompt
    from src.chat.message_receive.chat_manager import BotChatSession
    from src.chat.utils import scene_context
    generator.chat_stream = BotChatSession(session_id='s', platform='telegram', group_id='synthetic-identity', group_name='合成群')
    import os
    production_persona = os.environ.get('MAIBOT_TEST_PRODUCTION_PERSONA') == '1'
    persona_config = module.global_config
    monkeypatch.setattr(module, 'global_config', persona_config if production_persona else SimpleNamespace(
        bot=SimpleNamespace(nickname='合成助手', alias_names=[]),
        personality=SimpleNamespace(personality='', enable_identity_guard=True, reply_style='自然简洁'),
        experimental=SimpleNamespace(emotion_trait=None)))
    monkeypatch.setattr(module, 'build_personality_emotion_suffix', lambda _: '')
    monkeypatch.setattr(scene_context, '_load_account_profile', lambda: {})
    monkeypatch.setattr(generator, '_resolve_session_id', lambda _: 's')
    monkeypatch.setattr(generator, '_build_group_chat_attention_block', lambda _: '')
    generator._load_prompt = partial(load_prompt, locale='zh-CN', custom_prompts_root=Path('/tmp/nonexistent-sender-custom-prompts'))
    monkeypatch.setattr(generator, '_build_reply_attachment_prompt', lambda **kw: '')
    monkeypatch.setattr(generator, '_select_temporary_reply_style', lambda: '')
    def message(uid, mid, body):
        sequence = MessageSequence([])
        sequence.text(body)
        return SimpleNamespace(platform='telegram', message_id=mid, session_id='s',
            timestamp=datetime(2026,1,1), is_notify=False, raw_message=sequence,
            message_info=SimpleNamespace(user_info=SimpleNamespace(user_id=uid,user_nickname='同名',user_cardname='')))
    originals = [message('17','m1','我的猫叫松子。'), message('29','m2','我的兔子叫豆包。')]
    if corrected == 'dual':
        for uid, pet_name in [('17', '栗子'), ('29', '桃子')]:
            correction = message(uid, 'correction-' + uid, f'更正一下，我刚才把名字说错了，它叫{pet_name}；种类没说错。')
            if renamed and uid == target_uid:
                correction.message_info.user_info.user_nickname = '新昵称'
            originals.append(correction)
        expected = '猫，栗子' if target_uid == '17' else '兔子，桃子'
    elif corrected:
        correction = message(target_uid, 'm-correction', '更正一下，我刚才把名字说错了，它叫栗子；种类没说错。')
        if renamed:
            correction.message_info.user_info.user_nickname = '新昵称'
        originals.append(correction)
        expected = ('兔子' if target_uid == '29' else '猫') + '，栗子'
    target = message(target_uid,'m3','我养的是什么、叫什么？')
    if renamed:
        target.message_info.user_info.user_nickname = '新昵称'
    async def build():
        engine = object.__new__(MaisakaReasoningEngine)
        engine._runtime = SimpleNamespace(_is_focus_mode_active_for_current_chat=lambda: False)
        return [await engine._build_history_message(m, source_kind='user') for m in originals]
    history = asyncio.run(build())
    items = generator._build_request_messages(history, target, '', reply_requirements='只回答已知信息')
    wire = _convert_messages(items)
    def text(entry):
        content = entry.get('content')
        return content if isinstance(content, str) else ''.join(p.get('text','') for p in content or [])
    assert wire[0]['role'] == 'system'
    assert 'sender_id="17"' in text(wire[1]) and '松子' in text(wire[1])
    assert 'sender_id="29"' in text(wire[2]) and '豆包' in text(wire[2])
    if corrected == 'dual':
        assert 'sender_id="17"' in text(wire[3]) and '栗子' in text(wire[3])
        assert 'sender_id="29"' in text(wire[4]) and '桃子' in text(wire[4])
        assert '种类没说错。' in text(wire[3]) and '种类没说错。' in text(wire[4])
    elif corrected:
        assert f'sender_id="{target_uid}"' in text(wire[3])
        assert '它叫栗子；种类没说错。' in text(wire[3])
    final = text(wire[-1])
    assert wire[-1]['role'] == 'user'
    other_uid = '17' if target_uid == '29' else '29'
    assert f'sender_id="{target_uid}"' in final and f'sender_id="{other_uid}"' not in final
    assert 'sender_platform="telegram"' in final
    assert '我养的是什么、叫什么？' in final
    assert '只回答已知信息' in final
    # 导出真实装配请求供独立联网进程测试；沙箱自身保持断网。
    import os
    import json
    from pathlib import Path
    export = os.environ.get('MAIBOT_ASSEMBLED_PROMPT_OUTPUT')
    if export:
        name = 'sender-request.json' if target_uid == '29' else 'sender-request-first.json'
        if renamed:
            name = name.replace('.json', '-renamed.json')
        if corrected:
            name = name.replace('.json', '-dual.json' if corrected == 'dual' else '-corrected.json')
        path = Path(export)/name
        path.write_text(json.dumps({'scope':'real template/history/target assembly; isolated auxiliary inputs; persona source recorded in production_persona_config',
                                   'messages':wire,'expected':expected,'production_persona_config':production_persona},ensure_ascii=False))
        path.chmod(0o600)
