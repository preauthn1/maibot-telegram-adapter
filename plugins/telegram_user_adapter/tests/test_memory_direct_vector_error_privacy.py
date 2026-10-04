"""Direct vector ingest failure receipts must not retain provider text."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService


@pytest.mark.parametrize('stage', ['restore', 'encode'])
@pytest.mark.parametrize('allow_metadata_only', [True, False])
def test_direct_vector_failure_privacy(stage, allow_metadata_only):
    secret = 'SYNTHETIC_PRIVATE_PROVIDER_MARKER'
    error = OSError(secret)
    target = Mock()
    target.__contains__ = Mock(return_value=False)
    target.restore = Mock(side_effect=error if stage == 'restore' else None, return_value=0)
    enqueue = Mock()
    degraded = Mock()
    service = SimpleNamespace(
        _allow_metadata_only_write=lambda: allow_metadata_only,
        _paragraph_store=lambda: target,
        _enqueue_paragraph_vector_backfill=enqueue,
        embedding_manager=SimpleNamespace(encode=AsyncMock(side_effect=error)),
        _is_embedding_degraded=lambda: False,
        _embedding_fallback_enabled=lambda: True,
        _set_embedding_degraded=degraded,
    )
    call = MemoryIngestService._write_paragraph_vector_or_enqueue(
        service, paragraph_hash='synthetic-id', content='synthetic paragraph', context='synthetic'
    )
    if allow_metadata_only:
        result = asyncio.run(call)
        assert result['queued'] is True and result['vector_written'] is False
        assert secret not in repr(result)
        assert enqueue.call_count == 1
    else:
        with pytest.raises(OSError) as raised:
            asyncio.run(call)
        assert raised.value is error
        enqueue.assert_not_called()
    assert secret not in repr(enqueue.call_args_list)
    assert secret not in repr(degraded.call_args_list)
    target.add.assert_not_called()
