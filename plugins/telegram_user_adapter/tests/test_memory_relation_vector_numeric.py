"""Real SQLite relation states; synthetic embeddings and index receipts."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import numpy as np
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.utils.relation_write_service import RelationWriteService, _RelationVectorRecord


@pytest.mark.parametrize('value,valid', [
    ([[float('nan'), 1]], False), ([[float('inf'), 1]], False),
    ([[-float('inf'), 1]], False), ([[[]]], False), ([[]], False),
    (1, False), ([[1, 2], [3, 4]], False),
    ([1, 2], True), ([[1, 2]], True),
])
def test_relation_vector_numeric(tmp_path, value, valid):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        h = store.add_relation('甲', '喜欢', '乙')
        present = set()
        target = MagicMock()
        target.__contains__.side_effect = lambda key: key in present
        target.restore.return_value = 0
        target.add.side_effect = lambda **kw: present.update(kw['ids'])
        encoder = SimpleNamespace(batch_size=2, max_concurrent=1,
            encode_batch=AsyncMock(return_value=np.asarray(value)))
        writer = RelationWriteService(store, None, target, encoder)
        result = asyncio.run(writer._ensure_relation_vectors([
            _RelationVectorRecord(h, '甲', '喜欢', '乙')]))
        if valid:
            target.add.assert_called_once()
            assert result[0].vector_state == 'ready'
        else:
            target.add.assert_not_called()
            assert result[0].vector_state == 'failed'
        store.close(); store.connect()
        row = store.get_relation(h)
        assert row is not None
        assert row['vector_state'] == ('ready' if valid else 'failed')
        if not valid:
            assert 'relation_vector_write_failed:ValueError' in repr(row)
    finally:
        store.close()
