"""Single relation vector failures: actual SQLite, synthetic external dependencies."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock
import numpy as np
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.utils.relation_write_service import RelationWriteService


@pytest.mark.parametrize('stage', ['encode', 'add', 'authorize'])
def test_single_relation_error_privacy(tmp_path, monkeypatch, stage):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        h = store.add_relation('甲', '喜欢', '乙')
        error = OSError('SYNTHETIC_PRIVATE_SINGLE_RELATION')
        target = MagicMock()
        target.__contains__.return_value = False
        target.is_tombstoned.return_value = False
        target.add.side_effect = error
        encoder = SimpleNamespace(encode=AsyncMock(
            side_effect=error if stage == 'encode' else None,
            return_value=np.array([1., 0.])))
        log = Mock()
        monkeypatch.setattr('src.A_memorix.core.utils.relation_write_service.logger', log)
        writer = RelationWriteService(store, None, target, encoder)
        guard = Mock(side_effect=error) if stage == 'authorize' else Mock()
        call = writer.ensure_relation_vector(h, '甲', '喜欢', '乙', before_vector_write=guard)
        if stage == 'authorize':
            with pytest.raises(OSError) as caught:
                asyncio.run(call)
            assert caught.value is error
            target.add.assert_not_called()
        else:
            result = asyncio.run(call)
            assert result.vector_state == 'failed'
            if stage == 'encode':
                target.add.assert_not_called()
                guard.assert_not_called()
            else:
                target.add.assert_called_once()
                guard.assert_called_once()
        store.close(); store.connect()
        row = store.get_relation(h)
        assert row is not None
        assert 'SYNTHETIC_PRIVATE_SINGLE_RELATION' not in repr(row)
        assert 'SYNTHETIC_PRIVATE_SINGLE_RELATION' not in repr(log.mock_calls)
        if stage != 'authorize':
            assert row['vector_state'] == 'failed'
            assert 'relation_vector_write_failed:OSError' in repr(row)
    finally:
        store.close()
