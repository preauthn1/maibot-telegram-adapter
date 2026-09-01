"""Maisaka 空闲退避状态。"""

from typing import TYPE_CHECKING
import os
import time

from src.common.logger import get_logger
from src.config.config import global_config
from src.maisaka.mode_policy import is_idle_cycle_reason


def _is_unlimited_mode() -> bool:
    """是否处于极端实验模式（解除频率类限制）。

    与插件侧 telegram_user_adapter/unlimited_mode.py 读同一个环境变量。
    这里不 import 插件模块——主程序不应依赖插件。

    Returns:
        True 表示解除空闲退避。
    """

    return os.environ.get("TG_UNLIMITED_MODE", "").strip() in {
        "1",
        "true",
        "yes",
        "on",
    }

if TYPE_CHECKING:
    from src.maisaka.runtime import MaisakaHeartFlowChatting

logger = get_logger("maisaka_idle_backoff")

# 刚发过言后的「参与中」时长。真人在群里说完话，会继续留意对方的追问，
# 而不是立刻把这个话题关掉。
#
# 实测事故：账号在 18:41 回了两条谈额度的消息，随后对方连续追问
# 「我这个是超了？」「难道泄露了？」「为何会这样」，但因为没 @ 它，
# Planner 每次都判「不该我说」，退避一路升到 240 秒，看起来就像
# 聊到一半突然消失。
ENGAGEMENT_WINDOW_SECONDS = 180.0

# 参与窗口内允许的最大退避。仍然退避（避免刷屏），但不至于错过整段对话。
ENGAGEMENT_MAX_BACKOFF_SECONDS = 30.0

# 空闲计数的衰减周期。超过这段时间没有任何新消息，计数回退一级。
#
# 解决的问题：``_count`` 原本只在真正发言时才清零，而消息稀疏的群
# 很难凑够 ``bypass_pending_count`` 条来绕过退避，于是会长期卡在
# 封顶值。实测慢速群（某低频群、某大群）连续 14-35 分钟停在 300 秒，
# 而活跃群 1-4 分钟就能靠消息量自然绕过。
#
# 加入衰减后，群安静下来时退避会逐步回落，新话题开始时能更快跟上，
# 而不必等到攒够 6 条消息。
IDLE_DECAY_SECONDS = 300.0


class IdleBackoffController:
    """维护连续空闲结束后的消息触发退避。"""

    def __init__(self, runtime: "MaisakaHeartFlowChatting") -> None:
        self._runtime = runtime
        self._count = 0
        self._until = 0.0
        self._last_spoke_at = 0.0
        # 上次记账时刻，用于计算空闲计数的衰减。
        self._last_cycle_at = 0.0

    def _is_engaged(self) -> bool:
        """判断是否处于「刚发过言」的参与窗口内。

        Returns:
            bool: 距上次发言不足 ``ENGAGEMENT_WINDOW_SECONDS`` 时返回 ``True``。
        """

        if self._last_spoke_at <= 0:
            return False
        return (time.monotonic() - self._last_spoke_at) < ENGAGEMENT_WINDOW_SECONDS

    def _decay_idle_count(self) -> None:
        """按空闲时长回退连续计数。

        群安静下来时让退避逐步回落：每过 ``IDLE_DECAY_SECONDS`` 降一级。
        否则消息稀疏的群会一直卡在封顶值，等到有人开新话题时反应迟钝。
        """

        if self._count <= 0 or self._last_cycle_at <= 0:
            return

        elapsed = time.monotonic() - self._last_cycle_at
        if elapsed < IDLE_DECAY_SECONDS:
            return

        steps = int(elapsed // IDLE_DECAY_SECONDS)
        self._count = max(0, self._count - steps)

    def _get_backoff_seconds(self) -> float:
        base_seconds = max(0.0, float(global_config.chat.reply_timing.no_action_backoff_base_seconds))
        cap_seconds = max(0.0, float(global_config.chat.reply_timing.no_action_backoff_cap_seconds))
        if base_seconds <= 0 or cap_seconds <= 0:
            return 0.0
        start_count = max(1, int(global_config.chat.reply_timing.no_action_backoff_start_count))
        if self._count < start_count:
            return 0.0

        exponent = max(0, self._count - start_count)
        backoff = min(cap_seconds, base_seconds * (2**exponent))

        # 刚发过言时压低退避上限，避免聊到一半突然消失。
        if self._is_engaged():
            return min(backoff, ENGAGEMENT_MAX_BACKOFF_SECONDS)
        return backoff

    def reset(self) -> None:
        """清理连续空闲退避状态。"""
        self._count = 0
        self._until = 0.0
        self._last_cycle_at = 0.0

    def note_spoke(self) -> None:
        """记录本轮真的发言了，开启参与窗口。"""

        self._last_spoke_at = time.monotonic()

    def record_cycle_result(self, cycle_end_reason: str) -> None:
        """按整轮结束原因维护空闲退避状态。"""
        normalized_reason = str(cycle_end_reason).strip()
        if not is_idle_cycle_reason(normalized_reason):
            # 非空闲结束意味着这一轮真的做了动作（通常是发了言）。
            self.note_spoke()
            self.reset()
            return

        runtime = self._runtime
        if not runtime.chat_stream.is_group_session:
            self.reset()
            return

        # 先按空闲时长回退计数，再累加本轮。
        # 群冷下来一段时间后，退避应当逐步回落而不是永远卡在封顶。
        self._decay_idle_count()
        self._last_cycle_at = time.monotonic()

        self._count += 1
        backoff_seconds = self._get_backoff_seconds()
        if backoff_seconds <= 0:
            self._until = 0.0
            return

        self._until = time.monotonic() + backoff_seconds
        logger.info(
            f"{runtime.log_prefix} 连续空闲退避已更新: "
            "来源=planner "
            f"连续次数={self._count} "
            f"退避={backoff_seconds:.2f} 秒"
        )

    def should_delay(self, pending_count: int) -> bool:
        """判断当前消息触发是否应被空闲退避延迟。"""
        runtime = self._runtime
        if runtime._is_focus_mode_active_for_current_chat():
            self.reset()
            return False

        if not runtime.chat_stream.is_group_session:
            return False

        # 极端实验模式：解除空闲退避。
        #
        # 退避是实测拦截次数最多的一层（25 分钟内 7 次），
        # 会在群冷下来后逐级拉长 Planner 的触发间隔，
        # 表现为"真人开始说话了但我们要过很久才反应"。
        # record_cycle_result 仍照常记账，切回正常模式立即恢复。
        if _is_unlimited_mode():
            return False

        if self._until <= 0:
            return False

        remaining_seconds = self._until - time.monotonic()
        if remaining_seconds <= 0:
            self._until = 0.0
            return False

        bypass_pending_count = max(0, int(global_config.chat.reply_timing.no_action_backoff_bypass_pending_count))
        # 刚发过言时更容易被新消息打断：对方追问了两三句还不理，
        # 就是聊到一半人间蒸发。
        if self._is_engaged() and bypass_pending_count > 2:
            bypass_pending_count = 2
        if bypass_pending_count > 0 and pending_count >= bypass_pending_count:
            logger.info(
                f"{runtime.log_prefix} 空闲退避被待处理消息数绕过: "
                f"待处理={pending_count} 阈值={bypass_pending_count}"
            )
            return False

        logger.debug(f"{runtime.log_prefix} 空闲退避中，延迟 {remaining_seconds:.2f} 秒后再检查")
        runtime._defer_message_turn_check(remaining_seconds)
        return True
