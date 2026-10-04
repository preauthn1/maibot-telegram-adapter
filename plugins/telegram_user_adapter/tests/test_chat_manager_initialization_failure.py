"""启动恢复失败应传播，而不是把空上下文伪装成成功启动。"""
import asyncio
from unittest.mock import AsyncMock, Mock
import pytest
import importlib
module = importlib.import_module('src.chat.message_receive.chat_manager')


def test_initialize_propagates_restore_failure(monkeypatch):
    manager = module.ChatManager()
    failure = OSError('PRIVATE_DATABASE_PATH')
    loader = AsyncMock(side_effect=failure)
    monkeypatch.setattr(manager, 'load_all_sessions_from_db', loader)
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)
    with pytest.raises(OSError) as caught:
        asyncio.run(manager.initialize())
    assert caught.value is failure
    loader.assert_awaited_once()
    assert 'PRIVATE_DATABASE_PATH' not in str(logger.mock_calls)


def test_real_restore_wrapper_does_not_log_exception_details(monkeypatch):
    # 不替换异步包装层，确保真正经过 to_thread 和两层异常处理。
    manager = module.ChatManager()
    failure = OSError('PRIVATE_DATABASE_PATH')
    loader = Mock(side_effect=failure)
    monkeypatch.setattr(manager, '_load_sessions_from_db', loader)
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)
    with pytest.raises(OSError) as caught:
        asyncio.run(manager.initialize())
    assert caught.value is failure
    loader.assert_called_once()
    assert manager.sessions == {}
    assert 'PRIVATE_DATABASE_PATH' not in str(logger.mock_calls)
    assert 'OSError' in str(logger.mock_calls)


def test_initialize_keeps_successful_restoration(monkeypatch):
    manager = module.ChatManager()
    loader = AsyncMock()
    monkeypatch.setattr(manager, 'load_all_sessions_from_db', loader)
    asyncio.run(manager.initialize())
    loader.assert_awaited_once()
