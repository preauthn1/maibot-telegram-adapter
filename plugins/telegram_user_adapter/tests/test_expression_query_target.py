"""当前目标进入真实向量调用参数；向量服务和配置隔离。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from src.chat.replyer import maisaka_expression_selector as module


def test_vector_query_includes_latest_target(monkeypatch):
    selector = object.__new__(module.MaisakaExpressionSelector)
    monkeypatch.setattr(selector, '_use_vector_candidate_pool', lambda: True)
    monkeypatch.setattr(selector, '_has_embedding_model_configured', lambda: True)
    monkeypatch.setattr(module, 'global_config', SimpleNamespace(expression=SimpleNamespace(
        expression_vector_index_path='synthetic', expression_vector_candidate_pool_size=10)))
    candidates = [{'id': 1, 'situation': '倾诉', 'style': '简短共情'}]
    select = AsyncMock(return_value=candidates)
    monkeypatch.setattr(module.expression_vector_index, 'select_candidates', select)
    result = asyncio.run(selector._build_expression_candidate_pool(
        session_id='synthetic', reply_reason='旧任务排障', reply_tool_args={},
        all_candidates=candidates, target_message='现在只想吐槽，不要建议'))
    assert result == candidates
    kwargs = select.call_args.kwargs
    assert '现在只想吐槽，不要建议' in kwargs['query_text']
    assert kwargs['query_text'].startswith('当前回复目标：')
    assert kwargs['session_id'] == 'synthetic'
    assert kwargs['scoped_candidates'] is candidates
