"""合成向量驱动生产召回排序，不访问真实索引或 embedding API。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from typing import Any
import numpy as np
import pytest
from src.chat.replyer.expression_vector_index import ExpressionVectorIndex, IndexedExpression, expression_fingerprint
from src.services import embedding_service


@pytest.mark.parametrize('query_vector,expected', [([1., 0.], 1), ([0., 1.], 7)])
@pytest.mark.parametrize('mismatch', [None, 'model_name', 'model_identifier', 'api_provider', 'dimension', 'nan', 'infinity', 'zero', 'overflow'])
def test_query_direction_changes_top_candidate(monkeypatch, query_vector, expected, mismatch):
    index = object.__new__(ExpressionVectorIndex)
    index._update_lock = asyncio.Lock()
    candidates = [dict(id=i + 1, situation=f'情境{i}', style=f'表达{i}', count=1) for i in range(12)]
    vectors = np.array([[1., i * .02] for i in range(6)] + [[i * .02, 1.] for i in range(6)], dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    entries = [IndexedExpression(c['id'], c['situation'], c['style'], 1,
        expression_fingerprint(c['id'], c['situation'], c['style']),
        'synthetic', 'synthetic-model', 2, i // 6, i) for i, c in enumerate(candidates)]
    snapshot = SimpleNamespace(expressions=entries,
        profile_vectors={'synthetic': vectors},
        profile_cluster_centers={'synthetic': np.eye(2, dtype=np.float32)})
    monkeypatch.setattr(index, '_load_snapshot', lambda path: snapshot)
    monkeypatch.setattr(index, 'get_current_embedding_profile', AsyncMock(return_value=
        SimpleNamespace(marker='synthetic', dimension=2, model_name='synthetic-model',
                        model_identifier='synthetic-id', api_provider='synthetic-provider')))
    # 使用真实 profile 校验，验证同维度的模型/供应商漂移也会被拒绝。
    metadata: dict[str, Any] = dict(model_name='synthetic-model', model_identifier='synthetic-id',
                    api_provider='synthetic-provider', embedding=query_vector)
    invalid_vectors = {'nan': [float('nan'), 1.], 'infinity': [float('inf'), 1.],
                       'zero': [0., 0.], 'overflow': [3e38, 3e38]}
    if mismatch in invalid_vectors:
        metadata['embedding'] = invalid_vectors[mismatch]
    elif mismatch == 'dimension':
        metadata['embedding'] = [1., 0., 0.]
    elif mismatch:
        metadata[mismatch] = 'different'
    embed = AsyncMock(return_value=SimpleNamespace(**metadata))
    monkeypatch.setattr(embedding_service, 'EmbeddingServiceClient', lambda **kw: SimpleNamespace(embed_text=embed))
    call = lambda: asyncio.run(index.select_candidates(index_path='synthetic-unused', session_id='synthetic',
        query_text='当前意图', scoped_candidates=candidates, candidate_pool_size=3, cluster_pool_size=1))
    if mismatch is not None:
        mmr = Mock(side_effect=AssertionError('invalid vector reached ranking'))
        monkeypatch.setattr(index, '_select_by_mmr', mmr)
        expected_error = '向量' if mismatch in invalid_vectors else 'embedding profile'
        with pytest.raises(ValueError, match=expected_error):
            call()
        mmr.assert_not_called()
        embed.assert_awaited_once_with('当前意图', session_id='synthetic')
        return
    results = call()
    assert len(results) == 3
    assert results[0]['id'] == expected
    assert len({r['id'] for r in results}) == 3
    assert all(r['id'] in {c['id'] for c in candidates} for r in results)
    assert all('vector_index' not in r and 'score' not in r for r in results)
    embed.assert_awaited_once_with('当前意图', session_id='synthetic')
