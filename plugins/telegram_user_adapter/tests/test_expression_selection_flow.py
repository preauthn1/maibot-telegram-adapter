"""通过公开选择入口验证上下文到子代理的传递；数据库、候选召回和插件隔离。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector


import pytest


@pytest.mark.parametrize('limit', [None, 0])
def test_public_selection_routes_context(monkeypatch, limit):
    selector = object.__new__(MaisakaExpressionSelector)
    candidates = [{'id': i, 'situation': '倾诉', 'style': '简短共情'} for i in range(1, 11)]
    monkeypatch.setattr(selector, '_can_use_expressions', lambda _: True)
    monkeypatch.setattr(selector, '_load_all_expression_candidates', lambda _: candidates)
    monkeypatch.setattr(selector, '_build_expression_candidate_pool', AsyncMock(return_value=candidates))
    monkeypatch.setattr(selector, '_build_chat_info', lambda _: '之前请求排障')
    monkeypatch.setattr(selector, '_serialize_reply_message', lambda _: {})
    async def hook(name, **kwargs):
        if limit is not None:
            kwargs['max_num'] = limit
        return SimpleNamespace(aborted=False, kwargs=kwargs)
    monkeypatch.setattr(selector, '_get_runtime_manager', lambda: SimpleNamespace(invoke_hook=hook))
    runner = AsyncMock(return_value='{"selected_ids":[]}')
    result = asyncio.run(selector.select_for_reply(
        session_id='synthetic', chat_history=[],
        reply_message=SimpleNamespace(processed_plain_text='现在只想吐槽，不要建议'),
        reply_reason='用户改变意图', sub_agent_runner=runner))
    if limit == 0:
        runner.assert_not_awaited()
        assert result.selected_expression_ids == []
        assert not result.expression_habits
        return
    runner.assert_awaited_once()
    prompt = runner.call_args.args[0]
    assert '之前请求排障' not in prompt
    assert '执行器提供的会话上下文' in prompt
    assert '现在只想吐槽，不要建议' in prompt
    assert '用户改变意图' in prompt
    assert result.selected_expression_ids == []
    assert not result.expression_habits
