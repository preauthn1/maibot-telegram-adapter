"""向量故障回退保留会话范围，但不记录上游异常正文。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from src.chat.replyer import maisaka_expression_selector as module


def test_vector_failure_redacts_error_and_keeps_scope(monkeypatch):
    selector = object.__new__(module.MaisakaExpressionSelector)
    monkeypatch.setattr(selector, '_use_vector_candidate_pool', lambda: True)
    monkeypatch.setattr(selector, '_has_embedding_model_configured', lambda: True)
    monkeypatch.setattr(module, 'global_config', SimpleNamespace(expression=SimpleNamespace(
        expression_vector_index_path='synthetic', expression_vector_candidate_pool_size=10)))
    candidates = [{'id': 1, 'situation': '倾诉', 'style': '简短共情'}]
    sampler = Mock(return_value=candidates)
    monkeypatch.setattr(selector, '_sample_legacy_expression_candidates', sampler)
    monkeypatch.setattr(module.expression_vector_index, 'select_candidates',
        AsyncMock(side_effect=RuntimeError('PRIVATE_REQUEST_SENTINEL')))
    warning, exception = Mock(), Mock()
    monkeypatch.setattr(module.logger, 'warning', warning)
    monkeypatch.setattr(module.logger, 'exception', exception)
    result = asyncio.run(selector._build_expression_candidate_pool(
        session_id='PRIVATE_SESSION_SENTINEL', reply_reason='排障', reply_tool_args={},
        all_candidates=candidates, target_message='现在只想吐槽'))
    assert result is candidates
    sampler.assert_called_once_with(candidates)
    assert sampler.call_args.args[0] is candidates
    exception.assert_not_called()
    warning.assert_called_once()
    assert 'RuntimeError' in str(warning.call_args)
    assert 'PRIVATE_' not in str(warning.call_args)
