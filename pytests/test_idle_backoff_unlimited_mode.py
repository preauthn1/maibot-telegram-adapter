"""空闲退避的极端实验模式开关。

空闲退避在主程序（src/maisaka/idle_backoff.py），是实测拦截次数
最多的一层——25 分钟内 7 次，会在群冷下来后逐级拉长 Planner 触发
间隔，表现为"真人开始说话了但我们要过很久才反应"。

主程序不 import 插件模块，因此两侧各自读同一个环境变量。
本测试同时锁住"两侧语义一致"，避免日后其中一侧改了取值规则。
"""

from unittest.mock import MagicMock

import pytest

from plugins.telegram_user_adapter import unlimited_mode
from src.maisaka import idle_backoff as ib

_ENV_KEY = "TG_UNLIMITED_MODE"


@pytest.fixture
def controller():
    """构造一个处于退避中的群聊控制器。"""

    runtime = MagicMock()
    runtime.chat_stream.is_group_session = True
    runtime._is_focus_mode_active_for_current_chat.return_value = False
    runtime.log_prefix = "[test]"

    instance = ib.IdleBackoffController(runtime)
    # 手动置入一个远未到期的退避窗口
    instance._until = ib.time.monotonic() + 300.0
    return instance


def test_backoff_delays_in_normal_mode(monkeypatch, controller) -> None:
    """正常模式：退避窗口内必须仍然延迟。"""

    monkeypatch.delenv(_ENV_KEY, raising=False)

    assert controller.should_delay(pending_count=0) is True


def test_backoff_released_in_unlimited_mode(monkeypatch, controller) -> None:
    """实验模式：退避解除，立即放行。"""

    monkeypatch.setenv(_ENV_KEY, "1")

    assert controller.should_delay(pending_count=0) is False


def test_env_semantics_match_plugin_side(monkeypatch) -> None:
    """主程序与插件两侧对同一环境变量的解读必须一致。

    两边是各自独立实现（主程序不依赖插件），容易在日后分叉。
    """

    for value in ("1", "true", "yes", "on", "", "0", "false", "no", "maybe"):
        monkeypatch.setenv(_ENV_KEY, value)
        assert ib._is_unlimited_mode() == unlimited_mode.is_unlimited(), (
            f"取值 {value!r} 时两侧判断不一致"
        )
