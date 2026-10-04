"""Planner工具正文保真，默认预览兼容；全部为合成文本。"""
import pytest
from src.services.memory_service import MemorySearchResult, MemoryHit
from src.maisaka.builtin_tool.query_memory import _build_success_content

@pytest.mark.parametrize('text', ['  条件：\n\t下雨：不出门\n\t否则：去公园\n', '```python\nif rain:\n    stay_home()\n```', '甲\r\n\r\n乙  '])
def test_planner_memory_keeps_original_layout(text):
    result=MemorySearchResult(hits=[MemoryHit(content=text)])
    assert _build_success_content(result,limit=1)=='1. '+text


def test_default_preview_stays_compatible():
    result=MemorySearchResult(hits=[MemoryHit(content='  甲\n乙  ')])
    assert result.to_text()=='1. 甲 乙'


def test_planner_body_is_not_preview_truncated():
    text='合成记忆'*100+'\n  否定：不是用户本人。\n'
    result=MemorySearchResult(hits=[MemoryHit(content=text)])
    assert _build_success_content(result,limit=1)=='1. '+text
    assert result.to_text().endswith('...')
