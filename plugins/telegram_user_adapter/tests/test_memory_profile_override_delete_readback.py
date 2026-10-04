"""Deletion receipts require absence, even with an AFTER DELETE trigger."""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('entry', ['delete', 'empty'])
def test_override_recreated_during_delete_is_not_success(tmp_path, entry):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        original = s.set_person_profile_override('synthetic', 'original', updated_at=10)
        conn = s._conn
        assert conn is not None
        conn.execute("""CREATE TRIGGER recreate_override AFTER DELETE ON person_profile_overrides
            BEGIN INSERT INTO person_profile_overrides(person_id, override_text, updated_at, updated_by, source)
            VALUES(OLD.person_id, 'synthetic replacement', OLD.updated_at, OLD.updated_by, OLD.source); END""")
        conn.commit()
        def clear():
            if entry == 'delete':
                return s.delete_person_profile_override('synthetic')
            return s.set_person_profile_override('synthetic', '')
        with pytest.raises(RuntimeError, match='^profile_override_delete_readback_failed$'):
            clear()
        assert not conn.in_transaction
        conn.commit()
        s.close(); s.connect()
        assert s.get_person_profile_override('synthetic') == original
        conn = s._conn
        assert conn is not None
        conn.execute('DROP TRIGGER recreate_override'); conn.commit()
        clear()
        s.close(); s.connect()
        assert s.get_person_profile_override('synthetic') is None
    finally:
        s.close()
