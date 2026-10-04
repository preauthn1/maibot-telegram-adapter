"""Direct embedding boundary preserves nonblank text; synthetic dependencies."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import numpy as np
import pytest

from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService


@pytest.mark.parametrize('text', ['\n    code()\n\t', '  合成正文  ', '\t\n  '])
def test_direct_text_fidelity(text):
    target = MagicMock()
    target.__contains__.side_effect = [False, True]
    target.restore.return_value = 0
    encoder = AsyncMock(return_value=np.array([1., 2.]))
    enqueue = Mock()
    svc = SimpleNamespace(
        _allow_metadata_only_write=lambda: False,
        _paragraph_store=lambda: target,
        _enqueue_paragraph_vector_backfill=enqueue,
        embedding_manager=SimpleNamespace(encode=encoder),
        _is_embedding_degraded=lambda: False,
        _embedding_fallback_enabled=lambda: False,
    )
    result = asyncio.run(MemoryIngestService._write_paragraph_vector_or_enqueue(
        svc, paragraph_hash='synthetic', content=text))
    if text.strip():
        encoder.assert_awaited_once_with(text)
        assert result['vector_written'] is True
        target.add.assert_called_once()
    else:
        encoder.assert_not_awaited()
        target.add.assert_not_called()
        assert result['success'] is False
        assert result['detail'] == 'invalid_paragraph_input'
    enqueue.assert_not_called()
