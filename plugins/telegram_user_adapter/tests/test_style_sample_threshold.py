"""后台与CLI都必须拒绝无效采样门槛，且在读写画像前拒绝。"""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.style_profiles import derive_style_controls, sync_style_profiles


@pytest.mark.parametrize('threshold', [0, -1, True, 1.5, '20', None])
def test_invalid_threshold_rejected_before_sampling_or_io(tmp_path, threshold):
    def unreadable_samples():
        raise AssertionError('Samples consumed before validation')
        yield 'sample'
    with pytest.raises(ValueError, match='positive integer'):
        derive_style_controls(unreadable_samples(), min_samples=threshold)
    with pytest.raises(ValueError, match='positive integer'):
        sync_style_profiles(tmp_path / 'missing', min_samples=threshold)


def test_positive_threshold_keeps_empty_dataset_disabled():
    result = derive_style_controls([], min_samples=1)
    assert not result.style_enabled
    assert result.sample_count == 0
