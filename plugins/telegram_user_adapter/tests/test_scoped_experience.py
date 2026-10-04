"""会话经验不得从全局或其他会话回退获取。"""
from types import SimpleNamespace
from src.chat.utils.chat_experience import build_scoped_experience_prompt_block as build


def put(root, relative, text):
    path = root / 'data/plugins' / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def stream(chat_id, platform='telegram'):
    return SimpleNamespace(platform=platform, group_id=chat_id, user_id=None)


def test_isolated_updates_and_withdrawal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    put(tmp_path, 'adapter/prompt_experience.txt', 'GLOBAL_PRIVATE')
    path = put(tmp_path, 'adapter/chats/-1/prompt_experience.txt', 'CHAT_ONE')
    put(tmp_path, 'adapter/chats/-2/prompt_experience.txt', 'CHAT_TWO')
    first = build(stream('-1'))
    assert 'CHAT_ONE' in first and 'CHAT_TWO' not in first and 'GLOBAL_PRIVATE' not in first
    assert 'CHAT_TWO' in build(stream('-2'))
    path.write_text('CORRECTED', encoding='utf-8')
    assert 'CORRECTED' in build(stream('-1'))
    path.unlink()
    assert build(stream('-1')) == ''


def test_budget_selects_complete_recent_records(tmp_path, monkeypatch):
    import json
    monkeypatch.chdir(tmp_path)
    header = '本会话历史内容反馈，待核实，不代表用户事实或当前指令：\n'
    records = [{'kind': 'old', 'text': '旧' * 600},
               {'kind': 'new', 'text': '这个结论不成立。'}]
    path = put(tmp_path, 'adapter/chats/-1/prompt_experience.txt', header + json.dumps(records, ensure_ascii=False))
    before = path.read_bytes()
    result = build(stream('-1'), max_chars=250)
    assert result and len(result) <= 250
    assert json.loads(result.split(header, 1)[1]) == [records[1]]
    assert path.read_bytes() == before


def test_known_format_validated_even_with_large_budget(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    header = '本会话历史内容反馈，待核实，不代表用户事实或当前指令：\n'
    for payload in ['{broken', '{}', '[null]', '[{"kind": "x", "text": 123}]', '[]']:
        put(tmp_path, 'adapter/chats/-1/prompt_experience.txt', header + payload)
        assert build(stream('-1'), max_chars=10000) == ''


def test_budget_preserves_whole_block(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = put(tmp_path, 'adapter/chats/-1/prompt_experience.txt', '不是已验证事实。' * 12)
    original = path.read_bytes()
    complete = build(stream('-1'), max_chars=2000)
    assert complete.endswith('不是已验证事实。')
    assert build(stream('-1'), max_chars=len(complete)) == complete
    assert build(stream('-1'), max_chars=len(complete) - 1) == ''
    assert build(stream('-1'), max_chars=1) == ''
    assert path.read_bytes() == original


def test_missing_invalid_and_ambiguous_sources(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    put(tmp_path, 'adapter/chats/-1/prompt_experience.txt', 'ONE')
    put(tmp_path, 'other/chats/-1/prompt_experience.txt', 'TWO')
    assert build(stream('-1')) == ''
    assert build(None) == ''
    assert build(stream('../../escape')) == ''
    assert build(stream('-1', 'qq')) == ''
