"""人数规则来自真实回复器；核心人设、风格和SDK装配，未上线。"""
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
RULE = '代写和润色不得擅自确定人数。原文“我们”未明确人数时，保留“我们”或“咱们”，不要改成“咱俩、我们俩、两个人”。原文明示两人则可使用双人表达；明示三人或更多时保留该人数。只调整措辞，不增加事实。'
QUESTION = '把这句话润色成发给朋友的聊天消息，只输出正文：昨天我们一起把旧书整理好了，挺有成就感的。'

@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('template_fails', [False, True])
def test_count_candidate_real_request(monkeypatch, enabled, template_fails):
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
    seq = MessageSequence([])
    seq.text(QUESTION)
    target = SimpleNamespace(platform='telegram', message_id='style-target', session_id='s', timestamp=datetime(2026,1,1), is_notify=False, raw_message=seq,
        message_info=SimpleNamespace(user_info=SimpleNamespace(user_id='17',user_nickname='合成用户',user_cardname='')))
    wire = _convert_messages(generator._build_request_messages([], target, '', reply_requirements='只输出润色正文'))
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
        p = Path(export)/('assembled-count-on.json' if enabled else 'assembled-count-off.json')
        p.write_text(json.dumps({'scope':'actual loaded core persona; synthetic style settings; real style selector, template, target and request assembly; auxiliary inputs isolated', 'messages':wire, 'expected':'未指定人数保持未指定；仅输出润色正文'},ensure_ascii=False))
        p.chmod(0o600)
