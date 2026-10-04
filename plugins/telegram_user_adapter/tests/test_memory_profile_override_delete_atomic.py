"""Synthetic override deletion failures roll back through both entry points."""
import sqlite3
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('entry', ['delete', 'empty'])
def test_override_delete_failure_is_atomic(tmp_path, entry):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        original = s.set_person_profile_override('synthetic', 'original')
        conn = s._conn
        assert conn is not None
        conn.execute("CREATE TRIGGER fail_clear AFTER DELETE ON person_profile_overrides BEGIN SELECT RAISE(FAIL, 'synthetic failure'); END")
        conn.commit()
        def clear():
            if entry == 'delete':
                return s.delete_person_profile_override('synthetic')
            return s.set_person_profile_override('synthetic', '  ')
        with pytest.raises(sqlite3.IntegrityError):
            clear()
        assert not conn.in_transaction
        conn.commit()
        s.close(); s.connect()
        assert s.get_person_profile_override('synthetic') == original
        conn = s._conn
        assert conn is not None
        conn.execute('DROP TRIGGER fail_clear'); conn.commit()
        result = clear()
        if entry == 'delete':
            assert result is True
            assert clear() is False
        else:
            assert result['override_text'] == ''
        s.close(); s.connect()
        assert s.get_person_profile_override('synthetic') is None
    finally:
        s.close()
