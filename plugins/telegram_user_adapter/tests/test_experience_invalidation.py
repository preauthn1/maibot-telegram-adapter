"""修订与撤回的经验必须立即反映在下一次读取。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.chat.utils import chat_experience as module


def test_update_and_delete_invalidate_cached_experience(tmp_path, monkeypatch):
    path = tmp_path / 'experience.txt'
    path.write_text('旧推断', encoding='utf-8')
    monkeypatch.setattr(module, '_cache_value', '')
    monkeypatch.setattr(module, '_cache_at', 0.0)
    monkeypatch.setattr(module, '_cache_path', path)
    monkeypatch.setattr(module, '_resolve_experience_path', lambda: path if path.exists() else None)
    assert '旧推断' in module.build_experience_prompt_block()
    path.write_text('经过纠正的新参考', encoding='utf-8')
    result = module.build_experience_prompt_block()
    assert '旧推断' not in result
    assert '经过纠正的新参考' in result
    path.unlink()
    assert module.build_experience_prompt_block() == ''
