"""Malformed persisted cache timestamps must never pin stale profiles."""
import pytest
from src.A_memorix.core.utils.person_profile_service import PersonProfileService as Service


@pytest.mark.parametrize('field', ['expires_at', 'updated_at'])
@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), -float('inf'), 'invalid'])
def test_malformed_cache_time_is_stale(monkeypatch, field, value):
    monkeypatch.setattr('src.A_memorix.core.utils.person_profile_service.time.time', lambda: 50.0)
    snapshot = {'expires_at': None, 'updated_at': 0}
    snapshot[field] = value
    assert Service._is_snapshot_stale(snapshot, 100) is True


def test_cache_time_zero_and_expiry_boundary(monkeypatch):
    monkeypatch.setattr('src.A_memorix.core.utils.person_profile_service.time.time', lambda: 50.0)
    assert not Service._is_snapshot_stale({'expires_at': None, 'updated_at': 0}, 100)
    assert not Service._is_snapshot_stale({'expires_at': '51'}, 100)
    assert Service._is_snapshot_stale({'expires_at': 50}, 100)
    assert Service._is_snapshot_stale({'expires_at': 0}, 100)
