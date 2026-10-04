"""Manual profile changes remain subordinate to the caller's transaction."""
import asyncio
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


@pytest.mark.parametrize('operation', ['replace', 'delete', 'empty'])
@pytest.mark.parametrize('failure_type', [OSError, asyncio.CancelledError])
def test_override_outer_rollback(tmp_path, operation, failure_type):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        original = store.set_person_profile_override('synthetic', 'original', updated_at=10)
        failure = failure_type('synthetic outer failure')
        with pytest.raises(failure_type) as caught:
            with store.transaction(immediate=True):
                store.set_person_profile_override('synthetic-new', 'created', updated_at=20)
                if operation == 'replace':
                    store.set_person_profile_override('synthetic', 'replacement', updated_at=20)
                elif operation == 'delete':
                    assert store.delete_person_profile_override('synthetic')
                else:
                    store.set_person_profile_override('synthetic', '')
                raise failure
        assert caught.value is failure
        conn = store._conn
        assert conn is not None and not conn.in_transaction
        conn.commit()
        store.close(); store.connect()
        assert store.get_person_profile_override('synthetic') == original
        assert store.get_person_profile_override('synthetic-new') is None
        with store.transaction(immediate=True):
            store.set_person_profile_override('synthetic-new', 'created', updated_at=20)
            store.set_person_profile_override('synthetic', 'replacement', updated_at=20)
        store.close(); store.connect()
        assert store.get_person_profile_override('synthetic')['override_text'] == 'replacement'
        assert store.get_person_profile_override('synthetic-new')['override_text'] == 'created'
    finally:
        store.close()
