"""Failed manual-profile insert/update must not survive a later commit."""
import sqlite3
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('existing', [False, True])
def test_override_write_atomic(tmp_path, existing):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        before = s.set_person_profile_override('synthetic', 'original') if existing else None
        event = 'UPDATE' if existing else 'INSERT'
        s._conn.execute(f"CREATE TRIGGER fail_override AFTER {event} ON person_profile_overrides BEGIN SELECT RAISE(FAIL, 'synthetic failure'); END")
        s._conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            s.set_person_profile_override('synthetic', 'changed')
        assert not s._conn.in_transaction
        s._conn.commit()
        s.close(); s.connect()
        assert s.get_person_profile_override('synthetic') == before
        s._conn.execute('DROP TRIGGER fail_override'); s._conn.commit()
        after = s.set_person_profile_override('synthetic', 'changed')
        assert after['override_text'] == 'changed'
        s.close(); s.connect()
        assert s.get_person_profile_override('synthetic') == after
    finally:
        s.close()
