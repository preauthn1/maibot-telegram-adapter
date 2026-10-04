"""Direct ingest validates embeddings before index mutation; synthetic dependencies."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import numpy as np
import pytest

from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService


@pytest.mark.parametrize('value', [
    [[float('nan'), 1]], [[float('inf'), 1]], [[-float('inf'), 1]],
    [[[1, 2]]], [[]], [[1, 2], [3, 4]], 1,
])
@pytest.mark.parametrize('allow', [True, False])
def test_invalid_direct_embedding(value, allow):
    target = MagicMock()
    target.__contains__.return_value = False
    target.restore.return_value = 0
    enqueue = Mock()
    svc = SimpleNamespace(
        _allow_metadata_only_write=lambda: allow, _paragraph_store=lambda: target,
        _enqueue_paragraph_vector_backfill=enqueue,
        embedding_manager=SimpleNamespace(encode=AsyncMock(return_value=np.asarray(value))),
        _is_embedding_degraded=lambda: False, _embedding_fallback_enabled=lambda: False,
    )
    call = MemoryIngestService._write_paragraph_vector_or_enqueue(
        svc, paragraph_hash='synthetic', content='synthetic text')
    if allow:
        result = asyncio.run(call)
        assert result['queued'] is True and result['vector_written'] is False
        enqueue.assert_called_once_with('synthetic', error='paragraph_vector_write_failed:ValueError')
    else:
        with pytest.raises(ValueError, match='invalid_paragraph_embedding'):
            asyncio.run(call)
        enqueue.assert_not_called()
    target.add.assert_not_called()


@pytest.mark.parametrize('value', [np.array([1., 2.]), np.array([[1., 2.]])])
def test_valid_direct_embedding(value):
    target = MagicMock()
    target.__contains__.side_effect = [False, True]
    target.restore.return_value = 0
    svc = SimpleNamespace(
        _allow_metadata_only_write=lambda: False, _paragraph_store=lambda: target,
        embedding_manager=SimpleNamespace(encode=AsyncMock(return_value=value)),
        _is_embedding_degraded=lambda: False, _embedding_fallback_enabled=lambda: False,
    )
    result = asyncio.run(MemoryIngestService._write_paragraph_vector_or_enqueue(
        svc, paragraph_hash='synthetic', content='synthetic text'))
    assert result['vector_written'] is True and result['queued'] is False
    assert target.add.call_count == 1
    np.testing.assert_array_equal(target.add.call_args.kwargs['vectors'], [[1., 2.]])
