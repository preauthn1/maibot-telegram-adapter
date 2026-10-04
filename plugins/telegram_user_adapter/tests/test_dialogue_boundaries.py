"""明确拒绝和停止请求不能按空洞附和丢弃。"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.low_information import LowInformationGuard, is_low_information


@pytest.mark.parametrize('text', ['不弄', '不弄。', '别问了', '别问了别问了', '啊这个就别问了'])
def test_boundary_survives_exhausted_filler_budget(text):
    guard = LowInformationGuard(window_size=10, limit=2)
    guard.record('确实')
    guard.record('正常')
    assert not guard.allows('哈哈')
    assert not is_low_information(text)
    assert guard.allows(text)
    guard.record(text)
    assert not guard.allows('确实')


def test_uncertain_acknowledgement_is_not_automatically_exempted():
    guard = LowInformationGuard(limit=0)
    assert not guard.allows('好的')
    assert not guard.allows('嗯')
    assert guard.allows('好的，先备份再迁移')
