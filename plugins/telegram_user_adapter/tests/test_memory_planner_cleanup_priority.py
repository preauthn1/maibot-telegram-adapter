"""Request failures take precedence over secondary interrupt cleanup errors."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.maisaka import reasoning_engine as module

@pytest.mark.parametrize('primary_type', [OSError, asyncio.CancelledError])
@pytest.mark.parametrize('cleanup', ['unbind', 'reset', 'both'])
def test_primary_error_survives_cleanup(monkeypatch, primary_type, cleanup):
    engine = object.__new__(module.MaisakaReasoningEngine)
    original = primary_type('PRIVATE_PRIMARY')
    flags = []
    def setter(flag):
        flags.append(flag)
        if flag is None and cleanup in ('reset', 'both'):
            raise ValueError('PRIVATE_CLEANUP')
    unbind = Mock(side_effect=RuntimeError('PRIVATE_CLEANUP') if cleanup in ('unbind', 'both') else None)
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)
    engine._runtime = SimpleNamespace(
        _bind_planner_interrupt_flag=Mock(), _unbind_planner_interrupt_flag=unbind,
        _chat_loop_service=SimpleNamespace(set_interrupt_flag=setter, chat_loop_step=AsyncMock(side_effect=original)),
        _chat_history=[], _max_context_size=12)
    engine._active_logical_turn_id = 'synthetic'
    with pytest.raises(primary_type) as caught:
        asyncio.run(engine._run_interruptible_planner())
    assert caught.value is original
    assert len(flags) == 2 and flags[-1] is None
    unbind.assert_called_once()
    assert 'PRIVATE_' not in str(logger.mock_calls)
