"""自动反思不是事实，缓存不能突破当前预算。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.chat.utils import chat_experience as module


def test_cached_experience_respects_each_budget(tmp_path, monkeypatch):
    path = tmp_path / 'experience.txt'
    path.write_text('参考内容' * 100, encoding='utf-8')
    monkeypatch.setattr(module, '_cache_value', '')
    monkeypatch.setattr(module, '_cache_at', 0.0)
    monkeypatch.setattr(module, '_cache_path', path)
    assert len(module.build_experience_prompt_block(100)) == 100
    assert len(module.build_experience_prompt_block(20)) == 20
    assert len(module.build_experience_prompt_block(200)) == 200
    assert module.build_experience_prompt_block(0) == ''


def test_experience_is_labeled_as_unverified(tmp_path, monkeypatch):
    path = tmp_path / 'experience.txt'
    path.write_text('一次交互得到的推断', encoding='utf-8')
    monkeypatch.setattr(module, '_cache_value', '')
    monkeypatch.setattr(module, '_cache_at', 0.0)
    monkeypatch.setattr(module, '_cache_path', path)
    result = module.build_experience_prompt_block()
    assert '待核实' in result
    assert '不覆盖' in result
    assert '一次交互得到的推断' in result
