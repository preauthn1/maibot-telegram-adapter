"""真实请求装配保留短回复语义约束；模型及检索不在此测试范围。"""
from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator
from src.llm_models.payload_content.context_item import RoleType


def test_short_style_reaches_request_without_encouraging_truncation(monkeypatch):
    generator = object.__new__(BaseMaisakaReplyGenerator)
    # 隔离数据读取；请求编排和篇幅提示用生产实现。
    monkeypatch.setattr(generator, '_build_keyword_reaction_prompt', lambda **kw: '')
    monkeypatch.setattr(generator, '_build_system_prompt', lambda **kw: '合成系统提示')
    monkeypatch.setattr(generator, '_build_final_user_message', lambda **kw: '只回答：不是我的猫')
    monkeypatch.setattr(generator, '_select_temporary_reply_style', lambda: '')
    monkeypatch.setattr(generator, '_build_history_messages', lambda *args: [])
    items = generator._build_request_messages([], None, '', reply_tool_args={'reply_style': '简短表达'})
    assert getattr(items[0], 'role', None) == RoleType.System
    text = '\n'.join(getattr(part, 'text', '') for item in items
                     for part in getattr(item, 'parts', ()))
    assert '只回答：不是我的猫' in text
    assert '允许句子残缺' not in text
    assert '保留关键否定、条件、对象归属和必要步骤' in text
    assert '优先满足用户当前明确的内容和格式要求' in text


def test_latest_requirement_follows_all_style_modes(monkeypatch):
    generator = object.__new__(BaseMaisakaReplyGenerator)
    monkeypatch.setattr(generator, '_build_keyword_reaction_prompt', lambda **kw: '')
    monkeypatch.setattr(generator, '_build_system_prompt', lambda **kw: '合成系统提示')
    monkeypatch.setattr(generator, '_build_final_user_message', lambda **kw: '只回一个词：好')
    monkeypatch.setattr(generator, '_select_temporary_reply_style', lambda: '临时风格')
    monkeypatch.setattr(generator, '_build_history_messages', lambda *args: [])
    for style in ('简短表达', '正常回复', '长回复'):
        items = generator._build_request_messages([], None, '合成参考', reply_tool_args={'reply_style': style})
        last = ''.join(getattr(part, 'text', '') for part in getattr(items[-1], 'parts', ()))
        assert last == '只回一个词：好'


def test_real_final_message_assembly_preserves_requirements(monkeypatch):
    generator = object.__new__(BaseMaisakaReplyGenerator)
    monkeypatch.setattr(generator, '_build_keyword_reaction_prompt', lambda **kw: '合成关键词参考')
    monkeypatch.setattr(generator, '_build_system_prompt', lambda **kw: '合成系统提示')
    monkeypatch.setattr(generator, '_build_target_message_block', lambda _: '目标：小林养猫，我养狗')
    monkeypatch.setattr(generator, '_build_reply_attachment_prompt', lambda **kw: '合成附件说明')
    monkeypatch.setattr(generator, '_select_temporary_reply_style', lambda: '')
    monkeypatch.setattr(generator, '_build_history_messages', lambda *args: [])
    items = generator._build_request_messages(
        [], None, '', reply_requirements='只回答用户的宠物，不要改成助手的宠物',
        reply_tool_args={'reply_style': '简短表达'})
    texts = [''.join(getattr(p, 'text', '') for p in getattr(item, 'parts', ())) for item in items]
    assert len(texts) == 3
    assert '保留关键否定' in texts[1]
    for required in ('目标：小林养猫，我养狗', '只回答用户的宠物，不要改成助手的宠物',
                     '合成关键词参考', '【额外发送内容参考】\n合成附件说明'):
        assert texts[-1].count(required) == 1
    assert texts[-1].endswith(generator._build_reply_instruction())


def test_normal_style_stays_empty():
    assert BaseMaisakaReplyGenerator._build_requested_reply_style_message('正常回复') == ''
