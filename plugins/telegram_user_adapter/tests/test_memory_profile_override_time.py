"""Invalid manual override timestamps cannot write or clear stored profiles."""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('text', ['changed', ''])
@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), -float('inf'), 'invalid'])
def test_override_invalid_time_before_mutation(tmp_path, text, value):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        original = s.set_person_profile_override('synthetic', 'original', updated_at=0)
        conn = s._conn
        assert conn is not None
        changes = conn.total_changes
        with pytest.raises(ValueError, match='^invalid_profile_time$'):
            s.set_person_profile_override('synthetic', text, updated_at=value)
        assert conn.total_changes == changes
        assert not conn.in_transaction
        s.close(); s.connect()
        assert s.get_person_profile_override('synthetic') == original
        result = s.set_person_profile_override('synthetic', 'valid', updated_at='0')
        assert result['updated_at'] == 0
        s.close(); s.connect()
        assert s.get_person_profile_override('synthetic') == result
    finally:
        s.close()
