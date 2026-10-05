"""Maisaka 消息触发门控。"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, TYPE_CHECKING

import json
import os
import re
import threading
import time

from src.chat.message_receive.message import SessionMessage
from src.chat.utils.utils import is_bot_self
from src.common.logger import get_logger
from src.maisaka.state_model import get_state_store
from src.maisaka.reply_necessity import (
    REPLY_NECESSITY_TRIGGER_SCORE,
    ReplyNecessityInput,
    ReplyNecessityScore,
    score_reply_necessity,
)

if TYPE_CHECKING:
    from src.maisaka.runtime import MaisakaHeartFlowChatting


logger = get_logger("maisaka_turn_gates")

TurnGateDecision = Literal["trigger", "wait", "delay"]

# 门控决策结构化日志（影子观测，只记录不改变判定）。
# 与适配器 funnel 同样的隐私约束：只存 message_id / chat_id / 分数 / 布尔判定，绝不存消息正文。
_GATE_LOG_ROOT = Path(__file__).resolve().parents[2] / "data" / "gate_decisions"
_GATE_LOG_TZ = timezone(timedelta(hours=8))  # Asia/Shanghai，无夏令时
_GATE_LOG_LOCK = threading.Lock()
_GATE_LOG_WARN_EVERY = 100
_gate_log_failures = 0

# score_reply_necessity 只返回总分与 detail 文本；分项从 detail 中按固定格式提取，
# 再用"原始分 = 各分项之和"做一致性校验，格式漂移会以 breakdown_consistent=false 暴露出来。
_DETAIL_INT_FIELDS = {
    "raw_score": re.compile(r"原始=(-?\d+)"),
    "relevance": re.compile(r"强相关=(-?\d+)"),
    "content": re.compile(r"内容=(-?\d+)"),
    "presence_penalty": re.compile(r"存在感=-(\d+)"),
}
_DETAIL_FLOAT_FIELDS = {
    "effective_frequency": re.compile(r"(?<!\S)频率=(\d+(?:\.\d+)?)"),
    "frequency_factor": re.compile(r"倍率=(\d+(?:\.\d+)?)"),
}
_RELEVANCE_REASON_PATTERN = re.compile(r"强相关=-?\d+\(([^)]*)\)")
_CONTENT_REASON_PATTERN = re.compile(r"内容=-?\d+\(([^)]*)\)")


def _external_messages(pending_messages: Sequence[SessionMessage]) -> List[SessionMessage]:
    """过滤掉麦麦自己发出的消息。"""

    return [
        message
        for message in pending_messages
        if not is_bot_self(message.platform, message.message_info.user_info.user_id)
    ]


def _parse_necessity_breakdown(detail: str, pressure_score: int) -> Dict[str, Any]:
    """从必要性 detail 中提取各分项分数与命中类别（不含任何消息原文）。"""

    breakdown: Dict[str, Any] = {}
    for key, pattern in _DETAIL_INT_FIELDS.items():
        match = pattern.search(detail)
        # 分项为 0 时 detail 不输出该项
        breakdown[key] = int(match.group(1)) if match else 0
    for key, pattern in _DETAIL_FLOAT_FIELDS.items():
        match = pattern.search(detail)
        breakdown[key] = float(match.group(1)) if match else None
    breakdown["pressure"] = pressure_score

    relevance_match = _RELEVANCE_REASON_PATTERN.search(detail)
    breakdown["relevance_reason"] = relevance_match.group(1) if relevance_match else "普通"
    content_match = _CONTENT_REASON_PATTERN.search(detail)
    # 只保留类别标签（问题/请求/征询/长文本/短反应），去掉冒号后的命中词，避免任何文本落盘
    breakdown["content_tags"] = (
        [tag.split(":", 1)[0] for tag in content_match.group(1).split(",") if tag] if content_match else []
    )
    breakdown["breakdown_consistent"] = breakdown["raw_score"] == (
        breakdown["relevance"] + breakdown["content"] + breakdown["pressure"] - breakdown["presence_penalty"]
    )
    return breakdown


def _append_gate_decision(record: Dict[str, Any]) -> None:
    """追加一行门控决策 JSONL；目录 700、文件 600。"""

    now = datetime.now(_GATE_LOG_TZ)
    row = {"ts": now.isoformat(timespec="seconds"), "unix": round(time.time(), 3), **record}
    line = json.dumps(row, ensure_ascii=False) + "\n"
    path = _GATE_LOG_ROOT / f"{now:%Y-%m-%d}.jsonl"
    with _GATE_LOG_LOCK:
        _GATE_LOG_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(_GATE_LOG_ROOT, 0o700)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(line)


@dataclass(frozen=True)
class TurnGateResult:
    """单个触发门控的判定结果。"""

    decision: TurnGateDecision
    detail: str
    delay_seconds: Optional[float] = None
    pressure_score: Optional[int] = None

    @property
    def should_trigger(self) -> bool:
        return self.decision == "trigger"


class ReplyNecessityTurnGate:
    """按回复必要性评分决定是否进入 Planner。"""

    def __init__(self, runtime: "MaisakaHeartFlowChatting") -> None:
        self._runtime = runtime

    def score(
        self,
        *,
        pending_messages: Sequence[SessionMessage],
        trigger_threshold: int,
    ) -> ReplyNecessityScore:
        """按当前 runtime 快照为待处理消息计算回复必要性评分。"""

        runtime = self._runtime
        external_messages = _external_messages(pending_messages)
        average_interval = runtime._get_recent_average_external_message_interval()
        if average_interval is not None and average_interval > 0:
            last_external_received_at = runtime._last_external_message_received_at or runtime._last_message_received_at
            idle_seconds = max(0.0, time.time() - last_external_received_at)
            idle_reached_average = idle_seconds >= average_interval
        else:
            idle_seconds = 0.0
            idle_reached_average = False

        recent_self_replies, recent_window_messages = self._count_recent_presence_messages()
        return score_reply_necessity(
            ReplyNecessityInput(
                texts=[(message.processed_plain_text or "").strip() for message in external_messages],
                pending_count=len(external_messages),
                trigger_threshold=trigger_threshold,
                has_at=any(message.is_at for message in external_messages),
                has_mention=any(message.is_mentioned for message in external_messages),
                is_group_chat=runtime.chat_stream.is_group_session,
                focus_active=runtime._is_focus_mode_active_for_current_chat(),
                recent_self_replies=recent_self_replies,
                recent_window_messages=recent_window_messages,
                effective_frequency=runtime._get_effective_reply_frequency(),
                idle_seconds=idle_seconds,
                idle_reached_average=idle_reached_average,
            )
        )

    def evaluate(
        self,
        *,
        pending_messages: Sequence[SessionMessage],
        trigger_threshold: int,
    ) -> TurnGateResult:
        """返回回复必要性门控的触发判定。"""

        score_result = self.score(
            pending_messages=pending_messages,
            trigger_threshold=trigger_threshold,
        )
        # Phase 3.2：内在状态的有界加性分量（合计 ±25），逐项记录。
        state_parts = self._state_components(pending_messages)
        state_total = sum(state_parts.values())
        final_score = max(0, score_result.score + state_total)
        decision = "trigger" if final_score >= REPLY_NECESSITY_TRIGGER_SCORE else "wait"
        state_detail = ",".join(f"{k}={v:+d}" for k, v in state_parts.items() if v)
        gate_detail = (
            f"必要性: {score_result.detail} 状态={state_total:+d}({state_detail or '无'}) "
            f"合计={final_score} 评分阈值={REPLY_NECESSITY_TRIGGER_SCORE}"
        )
        self._record_decision(
            pending_messages=pending_messages,
            trigger_threshold=trigger_threshold,
            score_result=score_result,
            state_parts=state_parts,
            final_score=final_score,
            triggered=decision == "trigger",
        )
        return TurnGateResult(decision=decision, detail=gate_detail, pressure_score=score_result.pressure_score)

    def _record_decision(
        self,
        *,
        pending_messages: Sequence[SessionMessage],
        trigger_threshold: int,
        score_result: ReplyNecessityScore,
        state_parts: Dict[str, int],
        final_score: int,
        triggered: bool,
    ) -> None:
        """把本次门控的各分项与判定写入结构化日志（影子观测）。

        判定已在调用前算完，这里只做记录：写日志失败只降级为告警，不影响返回值；
        门控本身的计算异常发生在本方法之前，照常向上抛出，不会被这里吞掉。
        """

        global _gate_log_failures
        try:
            runtime = self._runtime
            chat_stream = runtime.chat_stream
            external_messages = _external_messages(pending_messages)
            breakdown = _parse_necessity_breakdown(score_result.detail, score_result.pressure_score)
            if not breakdown["breakdown_consistent"]:
                logger.warning(
                    f"{runtime.log_prefix} 门控日志分项与原始分不一致，"
                    f"reply_necessity detail 格式可能已变化: {score_result.detail}"
                )
            record: Dict[str, Any] = {
                "session_id": runtime.session_id,
                "chat_id": str(chat_stream.group_id or chat_stream.user_id or ""),
                "is_group": bool(chat_stream.is_group_session),
                "message_ids": [str(message.message_id) for message in external_messages],
                "last_message_id": str(external_messages[-1].message_id) if external_messages else None,
                "pending_count": len(external_messages),
                "trigger_threshold": trigger_threshold,
                "has_at": any(message.is_at for message in external_messages),
                "has_mention": any(message.is_mentioned for message in external_messages),
                **breakdown,
                "necessity_score": score_result.score,
                "state": dict(state_parts),
                "state_total": sum(state_parts.values()),
                "final_score": final_score,
                "score_threshold": REPLY_NECESSITY_TRIGGER_SCORE,
                "triggered": triggered,
            }
            _append_gate_decision(record)
        except Exception as exc:  # noqa: BLE001 - 观测日志失败不能影响门控主链路
            _gate_log_failures += 1
            if _gate_log_failures == 1 or _gate_log_failures % _GATE_LOG_WARN_EVERY == 0:
                logger.warning(f"门控决策日志写入失败（累计 {_gate_log_failures} 次）: {exc!r}")

    def _state_components(self, pending_messages: Sequence[SessionMessage]) -> dict:
        """读取聊天流状态分量；任何异常都退化为 0，不影响原有判定。"""

        try:
            external = _external_messages(pending_messages)
            return get_state_store().speak_components(
                self._runtime.session_id,
                user_ids=[str(message.message_info.user_info.user_id) for message in external],
                directed_at_us=any(message.is_at or message.is_mentioned for message in external),
            )
        except Exception:  # noqa: BLE001 - 状态模型是辅助信号，失败不能阻断主链路
            return {}

    def _count_recent_presence_messages(self, window_seconds: float = 300.0) -> tuple[int, int]:
        """统计最近一段时间内麦麦发言数和总消息数。"""

        now = datetime.now()
        recent_self_count = 0
        recent_total_count = 0
        for message in reversed(self._runtime._chat_history):
            if (now - message.timestamp).total_seconds() > window_seconds:
                break
            if not message.count_in_context:
                continue
            recent_total_count += 1
            if message.source == "guided_reply":
                recent_self_count += 1
        return recent_self_count, recent_total_count


class FrequencyThresholdTurnGate:
    """按回复频率折算消息阈值，并用空窗补偿辅助触发。"""

    def __init__(self, runtime: "MaisakaHeartFlowChatting") -> None:
        self._runtime = runtime

    def evaluate(
        self,
        *,
        pending_count: int,
        trigger_threshold: int,
    ) -> TurnGateResult:
        """返回频率阈值门控的触发判定。"""

        if pending_count >= trigger_threshold:
            return TurnGateResult(
                decision="trigger",
                detail=f"pending={pending_count} 达到阈值={trigger_threshold} 判定=进入Planner",
            )

        idle_compensation_triggered, delay_seconds, idle_detail = self._calculate_idle_compensation(
            pending_count=pending_count,
            trigger_threshold=trigger_threshold,
        )
        if idle_compensation_triggered:
            return TurnGateResult(
                decision="trigger",
                detail=f"{idle_detail} 判定=空窗补偿进入Planner",
            )

        if delay_seconds is not None:
            return TurnGateResult(
                decision="delay",
                detail=f"{idle_detail} 判定=延迟检查",
                delay_seconds=delay_seconds,
            )

        return TurnGateResult(decision="wait", detail=f"{idle_detail} 判定=等待更多消息")

    def _calculate_idle_compensation(
        self,
        *,
        pending_count: int,
        trigger_threshold: int,
    ) -> tuple[bool, Optional[float], str]:
        """在新消息不足阈值时，按空窗时间折算补齐触发条件，并返回下次检查延迟。

        空窗折算量被限制在 ``trigger_threshold - 1`` 以内，确保至少要有一条真实新消息
        才可能触发，杜绝纯靠沉默累积反复唤醒回复。
        """

        # 与下方折算封顶互为双保险：纯沉默（pending_count == 0）一律不触发。
        if pending_count < 1:
            return False, None, "pending=0，不允许纯沉默触发"

        runtime = self._runtime
        average_message_interval = runtime._get_recent_average_external_message_interval()
        if average_message_interval is None or average_message_interval <= 0:
            return False, None, "平均消息间隔不可用，无法进行空窗补偿"

        last_external_received_at = runtime._last_external_message_received_at or runtime._last_message_received_at
        idle_seconds = max(0.0, time.time() - last_external_received_at)
        # 即便空窗无限长，也不能让纯沉默跨过阈值。
        idle_equivalent_count = min(
            idle_seconds / average_message_interval,
            float(max(0, trigger_threshold - 1)),
        )
        equivalent_message_count = pending_count + idle_equivalent_count
        detail = (
            f"平均间隔={average_message_interval:.2f}s "
            f"空窗={idle_seconds:.2f}s "
            f"空窗折算={idle_equivalent_count:.2f} "
            f"等效消息数={equivalent_message_count:.2f}/{trigger_threshold}"
        )
        if equivalent_message_count >= trigger_threshold:
            return True, None, detail

        delay_seconds = max(0.0, (trigger_threshold - pending_count) * average_message_interval - idle_seconds)
        return False, delay_seconds, f"{detail} 延迟={delay_seconds:.2f}s"
