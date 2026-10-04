"""A stale request must not mutate the current interrupt controller state."""
import asyncio
import pytest
from src.maisaka.runtime import PlannerInterruptController

@pytest.mark.parametrize('interrupted', [False, True])
def test_stale_unbind_preserves_current_request(interrupted):
    controller = PlannerInterruptController()
    old, current = asyncio.Event(), asyncio.Event()
    controller.bind(old)
    assert controller.request(max_consecutive_count=3) == 'request'
    controller.bind(current)
    assert controller.request(max_consecutive_count=3) == 'request'
    assert controller.consecutive_count == 2
    controller.unbind(old, interrupted=interrupted)
    assert controller.consecutive_count == 2
    assert controller.request(max_consecutive_count=3) == 'duplicate'
    assert current.is_set()
    controller.unbind(current, interrupted=False)
    assert controller.request(max_consecutive_count=3) == 'idle'
    assert controller.consecutive_count == 0
