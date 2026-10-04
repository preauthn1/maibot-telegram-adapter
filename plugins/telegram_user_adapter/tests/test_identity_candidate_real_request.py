"""现实参与候选仅测试注入；真实模板/风格/SDK装配。"""
import asyncio
import json
import os
from datetime import datetime
from functools import partial
from pathlib import Path
from types import SimpleNamespace
import pytest
from src.chat.replyer import maisaka_generator_base as module
from src.chat.message_receive.chat_manager import BotChatSession
from src.chat.utils import scene_context
from src.common.prompt_i18n import load_prompt
from src.common.data_models.message_component_data_model import MessageSequence
from src.llm_models.model_client.openai_client import _convert_messages

STYLE = '活泼口语，多用感叹号，像朋友闲聊一样自然。'
RULE = '区分聊天记忆与现实参与：你能讨论、回顾聊天，但没有亲自和用户吃饭、爬山、合照等线下经历。遇到这种现实共同参与的前提，简短说明自己没参与，不说忘了、记不清、没记录，也不猜用户记错了谁；随后可回应其话题。明确虚构角色扮演和代写中的第一人称属于角色或委托者，不套用这项现实参与限制。'
QUESTION = '昨天你把那本书亲手递给我的时候，说了什么？'

@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('template_fails', [False, True])
def test_identity_candidate_real_request(monkeypatch, enabled, template_fails):
    generator = object.__new__(module.BaseMaisakaReplyGenerator)
    generator.chat_stream = BotChatSession(session_id='s', platform='telegram', group_id='synthetic-style', group_name='合成群')
    # 仅覆写风格候选与概率，核心人格仍为沙箱加载的配置。
    monkeypatch.setattr(module.global_config.personality, 'multiple_reply_style', [STYLE])
    monkeypatch.setattr(module.global_config.personality, 'multiple_probability', 1.0 if enabled else 0.0)
    monkeypatch.setattr(module.random, 'random', lambda: 0.5)
    monkeypatch.setattr(module.random, 'choice', lambda candidates: candidates[0])
    monkeypatch.setattr(module, 'is_bot_self', lambda *a: False)
    monkeypatch.setattr(module, 'build_personality_emotion_suffix', lambda _: '')
    monkeypatch.setattr(scene_context, '_load_account_profile', lambda: {})
    monkeypatch.setattr(generator, '_resolve_session_id', lambda _: 's')
    monkeypatch.setattr(generator, '_build_group_chat_attention_block', lambda _: '')
    monkeypatch.setattr(generator, '_build_reply_attachment_prompt', lambda **kw: '')
    monkeypatch.setattr(generator, '_build_keyword_reaction_prompt', lambda **kw: '')
    generator._load_prompt = partial(load_prompt, locale='zh-CN', custom_prompts_root=Path('/tmp/nonexistent-style-prompts'))
    if template_fails:
        original_load = generator._load_prompt
        def fail_reply_template(name, **kwargs):
            if name == 'maisaka_replyer':
                raise OSError('synthetic template failure')
            return original_load(name, **kwargs)
        monkeypatch.setattr(generator, '_load_prompt', fail_reply_template)
    original_system = generator._build_system_prompt
    monkeypatch.setattr(generator, '_build_system_prompt', lambda *a, **kw: original_system(*a, **kw)+'\n\n'+RULE)
    seq = MessageSequence([])
    seq.text(QUESTION)
    target = SimpleNamespace(platform='telegram', message_id='style-target', session_id='s', timestamp=datetime(2026,1,1), is_notify=False, raw_message=seq,
        message_info=SimpleNamespace(user_info=SimpleNamespace(user_id='17',user_nickname='合成用户',user_cardname='')))
    wire = _convert_messages(generator._build_request_messages([], target, '', reply_requirements=''))
    assert QUESTION in wire[-1]['content']
    assert wire[0]['content'].count(RULE)==1
    assert all(RULE not in m.get('content','') for m in wire[1:])
    styles = [m for m in wire if m.get('content') == '你的说话风格可以尝试：\n'+STYLE]
    assert len(styles) == int(enabled)
    assert wire[-1]['role'] == 'user' and wire[0]['role'] == 'system'
    if enabled:
        assert wire[-2] == styles[0]
    export = os.environ.get('MAIBOT_ASSEMBLED_PROMPT_OUTPUT')
    if template_fails:
        assert '回复模板加载失败' in wire[0]['content']
    if export and not template_fails:
        p = Path(export)/('assembled-identity-on.json' if enabled else 'assembled-identity-off.json')
        p.write_text(json.dumps({'scope':'actual loaded core persona; synthetic style settings; real style selector, template, target and request assembly; auxiliary inputs isolated', 'messages':wire, 'expected':'不暗示亲自线下递书，不虚构台词，不用遗忘解释'},ensure_ascii=False))
        p.chmod(0o600)
