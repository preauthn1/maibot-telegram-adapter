"""Real relation state persistence, synthetic encoder failure and vector store."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock
from types import SimpleNamespace
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.utils.relation_write_service import RelationWriteService, _RelationVectorRecord


def test_relation_vector_error_privacy(tmp_path, monkeypatch):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        h = store.add_relation('甲', '喜欢', '乙')
        target = MagicMock()
        target.__contains__.return_value = False
        target.restore.return_value = 0
        marker = 'SYNTHETIC_PRIVATE_RELATION_PROVIDER'
        encoder = SimpleNamespace(batch_size=2, max_concurrent=1,
            encode_batch=AsyncMock(side_effect=OSError(marker)))
        log = Mock()
        monkeypatch.setattr('src.A_memorix.core.utils.relation_write_service.logger', log)
        writer = RelationWriteService(store, None, target, encoder)
        result = asyncio.run(writer._ensure_relation_vectors([
            _RelationVectorRecord(h, '甲', '喜欢', '乙')]))
        assert result[0].vector_state == 'failed'
        target.add.assert_not_called()
        store.close(); store.connect()
        row = store.get_relation(h)
        assert row['vector_state'] == 'failed'
        assert marker not in repr(row)
        assert marker not in repr(log.mock_calls)
        assert 'relation_vector_write_failed:OSError' in repr(row)
    finally:
        store.close()
