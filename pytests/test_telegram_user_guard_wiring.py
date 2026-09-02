"""接线验证：五道新防护必须真的接进发送链路。

只测模块本身是不够的——skill 里记录过「写完模块没接线」复发多次，
表现是单元测试全绿但线上照旧出事。本测试直接扫发送链路源码，
确认每道防护都有调用点。
"""

from pathlib import Path

import pytest

_OUTBOUND = Path("plugins/telegram_user_adapter/codecs/outbound.py")
_CLIENT = Path("plugins/telegram_user_adapter/telegram_user_client.py")


@pytest.fixture(scope="module")
def outbound_source() -> str:
    return _OUTBOUND.read_text(encoding="utf-8")


class TestGuardsAreWired:
    """每道防护都必须在 outbound.py 里有实际调用。"""

    @pytest.mark.parametrize(
        "func,why",
        [
            ("strip_tool_markup", "工具标记泄漏（</arg_value></tool_call>）"),
            ("check_persona_consistency", "人设矛盾（自称刚高中毕业）"),
            ("merge_split_commands", "命令被拆成两条发出"),
            ("protect_commands", "命令与中文粘连"),
            ("format_command_segments", "代码块包裹 + parse_mode"),
            ("extract_command_urls", "编造的安装命令域名"),
        ],
    )
    def test_guard_is_called(self, outbound_source: str, func: str, why: str) -> None:
        """调用点必须存在，不能只 import 不用。"""

        assert f"{func}(" in outbound_source, f"{func} 未接线，防不住：{why}"

    def test_dns_verification_is_wired(self, outbound_source: str) -> None:
        """DNS 验证走 asyncio.to_thread，是函数引用而非直接调用。

        单独断言：它不能阻塞事件循环，所以必须以 to_thread 方式调度。
        """

        assert "verify_urls_resolvable" in outbound_source, "DNS 验证未接线"
        assert "asyncio.to_thread(" in outbound_source, (
            "DNS 解析是阻塞调用，必须用 asyncio.to_thread 调度，"
            "否则会卡住整个事件循环"
        )


class TestPresenceDecoupling:
    """在线状态必须与消息读取解耦。

    24 小时在线的根因：mark_read 每条消息调一次 API，
    Telegram 据此把账号续期在线 5 分钟。入站中位间隔 8.7 秒，
    全天 3813 次间隔只有 19 次 > 5 分钟。
    """

    def test_mark_read_checks_presence(self) -> None:
        """睡眠闸门必须在链路上第一个 API 调用之前。

        codex 审计指出的 P0：最初只在 mark_read 前加闸门，
        但 event.get_sender() 在它之前、每条消息都调，
        同样会把在线续期 5 分钟——等于闸门没加。
        """

        source = Path("plugins/telegram_user_adapter/plugin.py").read_text(
            encoding="utf-8"
        )

        assert "allows_read_receipt()" in source, (
            "入站链路未接作息闸门，账号会 24 小时在线"
        )

        gate_idx = source.index("allows_read_receipt()")
        # 这些都是会续期在线的 API 调用，必须全在闸门之后
        for api in (
            "await event.get_sender()",
            "await tg_client.mark_read(",
        ):
            api_idx = source.index(api)
            assert gate_idx < api_idx, (
                f"作息闸门必须在 {api} 之前，否则该调用会续期在线"
            )

    def test_reaction_path_has_gate(self) -> None:
        """表情回应是延迟任务，必须独立判断作息。

        codex 审计 P1：reserve 时可能还醒着，延迟几秒后已进入睡眠窗口；
        send_reaction / get_available_reactions 都会续期在线。
        """

        source = Path("plugins/telegram_user_adapter/plugin.py").read_text(
            encoding="utf-8"
        )

        reaction_start = source.index("async def _do_send_reaction")
        reaction_body = source[reaction_start:reaction_start + 2000]

        assert "allows_read_receipt()" in reaction_body, (
            "_do_send_reaction 缺作息闸门，睡眠时段点表情会续期在线"
        )
        assert "policy.release(" in reaction_body, (
            "早退时必须归还预占的表情额度"
        )

    def test_presence_watch_loop_exists(self) -> None:
        """必须有独立巡检——作息边界不一定正好有发言。"""

        source = Path("plugins/telegram_user_adapter/plugin.py").read_text(
            encoding="utf-8"
        )

        assert "_presence_watch_loop" in source
        assert "enforce_schedule()" in source

    def test_watch_task_is_cancelled_on_stop(self) -> None:
        """巡检任务必须在停止时取消，否则任务泄漏。"""

        source = Path("plugins/telegram_user_adapter/plugin.py").read_text(
            encoding="utf-8"
        )

        assert "presence_task.cancel()" in source

    def test_schedule_is_injected(self) -> None:
        """PresenceManager 必须收到调度器，而非自己硬编码作息。"""

        source = Path("plugins/telegram_user_adapter/plugin.py").read_text(
            encoding="utf-8"
        )

        assert "schedule=presence_schedule" in source

    def test_presence_no_longer_uses_deprecated_linger(self) -> None:
        """回归：不得再从配置读秒级驻留。

        online_linger_min/max 已废弃（4-15 秒实测无效）。
        """

        source = Path("plugins/telegram_user_adapter/plugin.py").read_text(
            encoding="utf-8"
        )

        assert "linger_min=behavior.online_linger_min" not in source
        assert "linger_max=behavior.online_linger_max" not in source


class TestParseModeSupport:
    """parse_mode 必须一路传到 Telethon。"""

    def test_client_accepts_parse_mode(self) -> None:
        source = _CLIENT.read_text(encoding="utf-8")

        assert "parse_mode" in source, "客户端不支持 parse_mode，代码块无法渲染"
        assert "parse_mode=parse_mode" in source, "parse_mode 没传给 Telethon"

    def test_outbound_passes_parse_mode(self, outbound_source: str) -> None:
        assert "parse_mode=parse_mode" in outbound_source


class TestIdentityGuardsNotGatedByExperiment:
    """身份类防护绝不能受实验模式开关影响。

    实验模式解除的是频率类限制。若身份防护也被开关罩住，
    实验期间就会裸奔——而上次封号走的正是身份暴露链路。
    """

    @pytest.mark.parametrize(
        "func",
        [
            "strip_tool_markup",
            "check_persona_consistency",
            "extract_command_urls",
        ],
    )
    def test_not_inside_unlimited_branch(self, outbound_source: str, func: str) -> None:
        """调用点不得出现在 is_unlimited() 分支内。"""

        idx = outbound_source.index(f"{func}(")
        # 往前找最近的 200 字符，不应有实验开关判断
        window = outbound_source[max(0, idx - 400):idx]

        assert "is_unlimited" not in window, (
            f"{func} 疑似被实验模式开关罩住，实验期间会失效"
        )

    def test_not_gated_by_humanize_flag(self, outbound_source: str) -> None:
        """身份防护也不该受 enable_humanize 控制。

        历史教训：这三道曾缩在 if self._enable_humanize 块内，
        关掉改写开关（本意只是"别改我的话"）会连带失去全部防护。
        """

        idx = outbound_source.index("strip_tool_markup(")
        window = outbound_source[max(0, idx - 300):idx]

        assert "if self._enable_humanize" not in window
