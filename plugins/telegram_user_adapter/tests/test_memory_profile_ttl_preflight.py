"""Invalid caller TTL is rejected before any profile work."""
import asyncio
from unittest.mock import Mock
import pytest
from src.A_memorix.core.utils.person_profile_service import PersonProfileService


@pytest.mark.parametrize('ttl', [True, False, float('nan'), float('inf'), -float('inf'), 'invalid'])
@pytest.mark.parametrize('force', [False, True])
def test_invalid_ttl_preflight(ttl, force):
    svc = object.__new__(PersonProfileService)
    svc.metadata_store = Mock()
    svc.get_person_aliases = Mock(side_effect=AssertionError('unexpected profile work'))
    with pytest.raises(ValueError, match='^invalid_profile_ttl$'):
        asyncio.run(svc.query_person_profile(person_id='synthetic', ttl_seconds=ttl, force_refresh=force))
    assert svc.metadata_store.mock_calls == []
    svc.get_person_aliases.assert_not_called()
