"""Interrupt setup failure must undo runtime binding before propagating."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from src.maisaka import reasoning_engine as module


def test_interrupt_setup_failure_cleans_binding():
    engine = object.__new__(module.MaisakaReasoningEngine)
    original = OSError('synthetic setup failure')
    flags = []
    bound = []
    def set_flag(flag):
        flags.append(flag)
        if flag is not None:
            raise original
    def bind(flag):
        bound.append(flag)
    unbind = Mock(side_effect=lambda flag, **kw: bound.remove(flag))
    request = AsyncMock()
    engine._runtime = SimpleNamespace(
        _bind_planner_interrupt_flag=bind,
        _unbind_planner_interrupt_flag=unbind,
        _chat_loop_service=SimpleNamespace(set_interrupt_flag=set_flag, chat_loop_step=request),
        _chat_history=[], _max_context_size=12)
    engine._active_logical_turn_id = 'synthetic-turn'
    with pytest.raises(OSError) as caught:
        asyncio.run(engine._run_interruptible_planner())
    assert caught.value is original
    assert bound == []
    assert len(flags) == 2 and flags[-1] is None
    unbind.assert_called_once_with(flags[0], interrupted=False)
    request.assert_not_awaited()
