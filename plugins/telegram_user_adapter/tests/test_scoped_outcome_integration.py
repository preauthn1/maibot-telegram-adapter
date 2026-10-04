"""真实反馈入口到会话经验读取的集成验证，使用隔离临时目录。"""
import asyncio
import importlib.util
import logging
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from src.chat.utils.chat_experience import build_scoped_experience_prompt_block


def load_store(monkeypatch):
    # 为相对导入建立隔离包，不执行适配器插件启动代码。
    name = '_scoped_outcome_fixture'
    package = types.ModuleType(name)
    package.__path__ = [str(Path(__file__).parents[1])]
    monkeypatch.setitem(sys.modules, name, package)
    spec = importlib.util.spec_from_file_location(name + '.self_improvement',
        Path(__file__).parents[1] / 'self_improvement.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_real_outcome_exports_only_its_chat(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = load_store(monkeypatch)
    base = tmp_path / 'data/plugins/adapter'
    store = module.SelfImprovementStore(base, logging.getLogger('test'))
    async def run():
        await store.record_outcome(module.ChatOutcome(chat_id='-1', text='FIRST_CONTENT', violation_kind='aggressive'))
        await store.record_outcome(module.ChatOutcome(chat_id='-2', text='SECOND_CONTENT', violation_kind='aggressive'))
    asyncio.run(run())
    for chat, own, other in [('-1', 'FIRST_CONTENT', 'SECOND_CONTENT'), ('-2', 'SECOND_CONTENT', 'FIRST_CONTENT')]:
        text = build_scoped_experience_prompt_block(SimpleNamespace(platform='telegram', group_id=chat, user_id=None))
        assert own in text and other not in text
        assert '待核实' in text
    assert not list(base.glob('chats/*/.experience-*'))


def test_reconstructed_store_restores_attribution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = load_store(monkeypatch)
    base = tmp_path / 'data/plugins/adapter'
    first = module.SelfImprovementStore(base, logging.getLogger('test'))
    asyncio.run(first.record_outcome(module.ChatOutcome(
        chat_id='-1', text='PERSISTED_ONE', violation_kind='aggressive')))
    asyncio.run(first.record_outcome(module.ChatOutcome(
        chat_id='-2', text='PERSISTED_TWO', violation_kind='aggressive')))
    # 删除导出物，排除仅仅读到了上个实例遗留文件的假阳性。
    (base / 'chats/-1/prompt_experience.txt').unlink()
    second = module.SelfImprovementStore(base, logging.getLogger('test'))
    asyncio.run(second.record_outcome(module.ChatOutcome(chat_id='-1', text='NORMAL', got_reply=True)))
    text = build_scoped_experience_prompt_block(SimpleNamespace(
        platform='telegram', group_id='-1', user_id=None))
    assert 'PERSISTED_ONE' in text
    assert 'PERSISTED_TWO' not in text and 'NORMAL' not in text


def test_long_feedback_survives_storage_export_and_read(tmp_path, monkeypatch):
    import json
    monkeypatch.chdir(tmp_path)
    module = load_store(monkeypatch)
    base = tmp_path / 'data/plugins/adapter'
    store = module.SelfImprovementStore(base, logging.getLogger('test'))
    original = '背景描述' * 55 + '但这个结论不成立。'
    asyncio.run(store.record_outcome(module.ChatOutcome(
        chat_id='-1', text=original, violation_kind='aggressive')))
    state = json.loads((base / 'self_improvement_state.json').read_text())
    assert state['violation_samples'][-1]['our_text'] == original
    exported = (base / 'chats/-1/prompt_experience.txt').read_text()
    assert json.loads(exported.split('\n', 1)[1])[0]['text'] == original
    session = SimpleNamespace(platform='telegram', group_id='-1', user_id=None)
    assert original in build_scoped_experience_prompt_block(session, max_chars=2000)
    assert build_scoped_experience_prompt_block(session, max_chars=100) == ''


def test_gathered_feedback_keeps_counts_and_attribution(tmp_path, monkeypatch):
    import json
    monkeypatch.chdir(tmp_path)
    module = load_store(monkeypatch)
    base = tmp_path / 'data/plugins/adapter'
    store = module.SelfImprovementStore(base, logging.getLogger('test'))
    async def run():
        await asyncio.gather(*(store.record_outcome(module.ChatOutcome(
            chat_id=str(-1 - i % 2), text=f'CHAT_{i % 2}_ITEM_{i}',
            violation_kind='aggressive')) for i in range(20)))
    asyncio.run(run())
    state = json.loads((base / 'self_improvement_state.json').read_text())
    assert state['total_messages'] == 20
    assert state['violation_aggressive'] == 20
    assert len(state['violation_samples']) == 20
    for group in range(2):
        path = base / 'chats' / str(-1 - group) / 'prompt_experience.txt'
        records = json.loads(path.read_text().split('\n', 1)[1])
        assert len(records) == 5
        assert all(r['text'].startswith(f'CHAT_{group}_') for r in records)
    assert not list(base.glob('chats/*/.experience-*'))


def test_disabled_store_does_not_export(tmp_path, monkeypatch):
    module = load_store(monkeypatch)
    base = tmp_path / 'disabled'
    store = module.SelfImprovementStore(base, logging.getLogger('test'), enabled=False)
    asyncio.run(store.record_outcome(module.ChatOutcome(chat_id='-1', text='UNWRITTEN', violation_kind='aggressive')))
    assert not base.exists()
