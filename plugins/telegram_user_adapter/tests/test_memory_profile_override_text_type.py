"""Wrong override types must not clear or replace a stored manual profile."""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('value', [None, False, True, 0, 42, {}, {'text': 'synthetic'}, [], ['synthetic'], b'synthetic'])
def test_override_text_type_preflight(tmp_path, value):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        original = s.set_person_profile_override('synthetic', 'original')
        conn = s._conn
        assert conn is not None
        changes = conn.total_changes
        with pytest.raises(ValueError, match='^invalid_profile_override_text$'):
            s.set_person_profile_override('synthetic', value)
        assert conn.total_changes == changes
        assert not conn.in_transaction
        s.close(); s.connect()
        assert s.get_person_profile_override('synthetic') == original
        cleared = s.set_person_profile_override('synthetic', '')
        assert cleared['override_text'] == ''
        s.close(); s.connect()
        assert s.get_person_profile_override('synthetic') is None
    finally:
        s.close()
