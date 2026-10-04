"""Manual overrides require matching persisted readback before commit."""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('fault', ['missing', 'person', 'text', 'time', 'author', 'source'])
def test_override_readback_failure_rolls_back(tmp_path, monkeypatch, fault):
    store = MetadataStore(data_dir=tmp_path); store.connect()
    try:
        original = store.set_person_profile_override('synthetic', 'original', updated_at=10)
        reader = store.get_person_profile_override
        def faulty(pid):
            if fault == 'missing':
                return None
            result = reader(pid)
            assert result is not None
            field = {'person': 'person_id', 'text': 'override_text', 'time': 'updated_at',
                     'author': 'updated_by', 'source': 'source'}[fault]
            result[field] = -1 if fault == 'time' else 'wrong synthetic value'
            return result
        monkeypatch.setattr(store, 'get_person_profile_override', faulty)
        with pytest.raises(RuntimeError, match='^profile_override_readback_failed$'):
            store.set_person_profile_override('synthetic', 'changed', updated_at=20,
                                              updated_by='synthetic-author', source='synthetic-source')
        conn = store._conn
        assert conn is not None and not conn.in_transaction
        conn.commit()
        monkeypatch.setattr(store, 'get_person_profile_override', reader)
        store.close(); store.connect()
        assert reader('synthetic') == original
        result = store.set_person_profile_override('synthetic', 'changed', updated_at=20,
                                                   updated_by='synthetic-author', source='synthetic-source')
        store.close(); store.connect()
        assert reader('synthetic') == result
        assert result['override_text'] == 'changed'
    finally:
        store.close()
