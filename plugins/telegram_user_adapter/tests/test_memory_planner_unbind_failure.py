"""A failing runtime unbind must not skip chat-loop flag reset."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.maisaka import reasoning_engine as module


def test_unbind_failure_still_resets_loop_flag():
    engine = object.__new__(module.MaisakaReasoningEngine)
    failure = OSError('synthetic unbind failure')
    flags = []
    request = AsyncMock(return_value=object())
    unbind = Mock(side_effect=failure)
    engine._runtime = SimpleNamespace(
        _bind_planner_interrupt_flag=Mock(),
        _unbind_planner_interrupt_flag=unbind,
        _chat_loop_service=SimpleNamespace(set_interrupt_flag=flags.append, chat_loop_step=request),
        _chat_history=[], _max_context_size=12)
    engine._active_logical_turn_id = 'synthetic'
    with pytest.raises(OSError) as caught:
        asyncio.run(engine._run_interruptible_planner())
    assert caught.value is failure
    assert len(flags) == 2 and flags[-1] is None
    assert isinstance(flags[0], asyncio.Event)
    unbind.assert_called_once_with(flags[0], interrupted=False)
    request.assert_awaited_once()
