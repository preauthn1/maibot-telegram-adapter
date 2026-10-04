"""每聊天流内在状态（升级计划 Phase 3 / 4 / 5）。

参考 erii（冲动/疲劳/刺激/心流）与 MoFox（post_reply_boost、等待状态机、
动态心情、rapport）。原则：

- 按聊天流隔离；时长用 ``time.monotonic()``，持久化时间用显式 Asia/Shanghai。
- 所有数值有上下限、按时间衰减回基线，重启可恢复。
- 只由事件和规则更新，不让 LLM 自由改数值。
- 对回复决策只输出**有界加性**分量（合计 ±STATE_SCORE_CAP），并逐项记录；
  不新增未知倍率，避免"每道模块都合理、乘积把机器人压死"。
- 心情只作为 prompt 的一小段辅助信息，不决定内容；rapport 只影响回复必要性
  与主动发言概率，不影响事实判断和安全策略，也不当作真实心理事实。
- 不绕过发送预算、跨群焦点、权限和身份安全闸门（这些在别处执行）。
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

import json
import math
import threading
import time

CN_TZ = timezone(timedelta(hours=8))
STATE_SCORE_CAP = 25

# 衰减半衰期（秒）。
_HALF_LIFE = {
    "fatigue": 20 * 60,
    "stimulus": 5 * 60,
    "flow": 4 * 60,
    "post_reply": 90,
    "valence": 60 * 60,
    "arousal": 15 * 60,
}
_BASELINE = {"energy": 0.7, "valence": 0.0, "arousal": 0.3}

# 等待状态机。
WAIT_MIN_SECONDS = 30
WAIT_MAX_SECONDS = 1800
WAIT_COOLDOWN_AFTER_UNANSWERED = 3
WAIT_COOLDOWN_SECONDS = 30 * 60


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _decay(value: float, baseline: float, elapsed: float, half_life: float) -> float:
    if elapsed <= 0 or half_life <= 0:
        return value
    factor = math.pow(0.5, elapsed / half_life)
    return baseline + (value - baseline) * factor


@dataclass
class WaitExpectation:
    """我方发出一条有明确期待的消息后的等待记录。"""

    expected_reply_type: str = "none"  # answer / confirmation / continuation / none
    max_wait_seconds: float = 0.0
    waiting_reason: str = ""
    started_mono: float = 0.0
    target_user_id: str = ""

    def active(self) -> bool:
        return self.expected_reply_type != "none" and self.started_mono > 0


@dataclass
class ChatState:
    """单个聊天流的状态。"""

    energy: float = 0.7
    fatigue: float = 0.0
    stimulus: float = 0.0
    valence: float = 0.0
    arousal: float = 0.3
    flow: float = 0.0
    post_reply: float = 0.0
    rapport: Dict[str, float] = field(default_factory=dict)
    rapport_updated: Dict[str, str] = field(default_factory=dict)
    unanswered_count: int = 0
    cooldown_until_mono: float = 0.0
    wait: WaitExpectation = field(default_factory=WaitExpectation)
    last_update_mono: float = 0.0
    last_external_mono: float = 0.0
    last_self_mono: float = 0.0
    last_event: str = ""
    last_event_at: str = ""

    # ---- 衰减 ----
    def tick(self, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        if self.last_update_mono <= 0:
            self.last_update_mono = now
            return
        elapsed = now - self.last_update_mono
        if elapsed <= 0:
            return
        self.fatigue = _decay(self.fatigue, 0.0, elapsed, _HALF_LIFE["fatigue"])
        self.stimulus = _decay(self.stimulus, 0.0, elapsed, _HALF_LIFE["stimulus"])
        self.flow = _decay(self.flow, 0.0, elapsed, _HALF_LIFE["flow"])
        self.post_reply = _decay(self.post_reply, 0.0, elapsed, _HALF_LIFE["post_reply"])
        self.valence = _decay(self.valence, _BASELINE["valence"], elapsed, _HALF_LIFE["valence"])
        self.arousal = _decay(self.arousal, _BASELINE["arousal"], elapsed, _HALF_LIFE["arousal"])
        # 能量随疲劳回落而回升。
        self.energy = _clamp(1.0 - 0.6 * self.fatigue, 0.1, 1.0)
        self.last_update_mono = now


class ChatStateStore:
    """进程内状态表 + JSON 持久化（原子替换写）。"""

    def __init__(self, path: Optional[Path]) -> None:
        self._path = path
        self._states: Dict[str, ChatState] = {}
        self._lock = threading.Lock()
        self._dirty = False
        self._last_flush = 0.0
        self._load()

    # ---- 持久化 ----
    def _load(self) -> None:
        if self._path is None or not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        now = time.monotonic()
        saved_unix = float(raw.get("saved_unix", 0.0) or 0.0)
        offline = max(0.0, time.time() - saved_unix) if saved_unix else 0.0
        for key, data in (raw.get("chats") or {}).items():
            wait = WaitExpectation(**{k: v for k, v in (data.pop("wait", {}) or {}).items()
                                      if k in WaitExpectation.__dataclass_fields__})
            state = ChatState(**{k: v for k, v in data.items() if k in ChatState.__dataclass_fields__})
            # 单调时钟不跨进程：把离线时长折算为"已过去的时间"，再把基准重置到现在。
            state.last_update_mono = now - offline
            state.tick(now)
            remaining_cd = state.cooldown_until_mono  # 持久化里存的是剩余秒数
            state.cooldown_until_mono = now + max(0.0, remaining_cd - offline) if remaining_cd > 0 else 0.0
            wait.started_mono = 0.0  # 等待不跨重启延续
            wait.expected_reply_type = "none"
            state.wait = wait
            state.last_external_mono = 0.0
            state.last_self_mono = 0.0
            self._states[key] = state

    def flush(self, force: bool = False) -> None:
        if self._path is None or not self._dirty:
            return
        now = time.monotonic()
        if not force and now - self._last_flush < 30:
            return
        with self._lock:
            payload = {"saved_unix": time.time(), "saved_at": datetime.now(CN_TZ).isoformat(), "chats": {}}
            for key, state in self._states.items():
                data = asdict(state)
                data["cooldown_until_mono"] = max(0.0, state.cooldown_until_mono - now)
                payload["chats"][key] = data
            self._dirty = False
            self._last_flush = now
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self._path)

    # ---- 访问 ----
    def get(self, chat_key: str, now: Optional[float] = None) -> ChatState:
        with self._lock:
            state = self._states.get(chat_key)
            if state is None:
                state = ChatState()
                self._states[chat_key] = state
            state.tick(now)
            return state

    def _mark(self, state: ChatState, event: str) -> None:
        state.last_event = event
        state.last_event_at = datetime.now(CN_TZ).isoformat(timespec="seconds")
        self._dirty = True

    # ---- 事件（Phase 3/5） ----
    def on_external_message(
        self,
        chat_key: str,
        *,
        user_id: str,
        directed_at_us: bool,
        is_question: bool,
        text_len: int,
        now: Optional[float] = None,
    ) -> Optional[str]:
        """群友发言。返回等待状态机事件：``reply_normal`` / ``reply_late`` / None。"""

        now = time.monotonic() if now is None else now
        state = self.get(chat_key, now)
        gap = now - state.last_external_mono if state.last_external_mono > 0 else 999.0
        state.last_external_mono = now
        # 新鲜度：间隔越长新消息越"刺激"，刷屏时刺激递减。
        state.stimulus = _clamp(state.stimulus + (0.25 if gap > 60 else 0.08), 0.0, 1.0)
        state.arousal = _clamp(state.arousal + 0.03, 0.0, 1.0)

        wait_event: Optional[str] = None
        if directed_at_us:
            state.flow = _clamp(state.flow + 0.3, 0.0, 1.0)
            state.unanswered_count = 0
            self._bump_rapport(state, user_id, 0.04)
            state.valence = _clamp(state.valence + 0.05, -1.0, 1.0)
            if state.wait.active():
                waited = now - state.wait.started_mono
                wait_event = "reply_late" if waited > state.wait.max_wait_seconds else "reply_normal"
                state.wait = WaitExpectation()
        elif state.wait.active() and state.wait.target_user_id and user_id == state.wait.target_user_id:
            # 目标用户发言但未指向我们：视作"看到了但没接"，不算回应。
            pass
        self._mark(state, "external")
        return wait_event

    def on_self_reply(
        self,
        chat_key: str,
        *,
        text: str,
        target_user_id: str = "",
        now: Optional[float] = None,
    ) -> None:
        """我方一条消息平台发送成功（Phase 3.3 post_reply_boost + Phase 4 记录期待）。"""

        now = time.monotonic() if now is None else now
        state = self.get(chat_key, now)
        state.last_self_mono = now
        state.fatigue = _clamp(state.fatigue + 0.15, 0.0, 1.0)
        state.post_reply = 1.0
        state.flow = _clamp(state.flow + 0.1, 0.0, 1.0)
        stripped = (text or "").strip()
        if stripped.endswith(("?", "？", "吗", "呢", "么")):
            expected, wait_s = "answer", 180.0
        elif stripped.endswith(("吧", "不", "没")):
            expected, wait_s = "confirmation", 120.0
        else:
            expected, wait_s = "none", 0.0
        if expected != "none":
            state.wait = WaitExpectation(
                expected_reply_type=expected,
                max_wait_seconds=_clamp(wait_s, WAIT_MIN_SECONDS, WAIT_MAX_SECONDS),
                waiting_reason="self_question",
                started_mono=now,
                target_user_id=target_user_id,
            )
        self._mark(state, "self_reply")

    def on_rejection(self, chat_key: str, *, user_id: str) -> None:
        """被叫闭嘴/明确拒绝（Phase 5）。"""

        state = self.get(chat_key)
        state.valence = _clamp(state.valence - 0.3, -1.0, 1.0)
        state.fatigue = _clamp(state.fatigue + 0.3, 0.0, 1.0)
        self._bump_rapport(state, user_id, -0.15)
        state.cooldown_until_mono = time.monotonic() + WAIT_COOLDOWN_SECONDS
        self._mark(state, "rejection")

    def on_correction(self, chat_key: str, *, user_id: str) -> None:
        """被纠正：轻微低落，但纠正本身是认真互动，rapport 不降。"""

        state = self.get(chat_key)
        state.valence = _clamp(state.valence - 0.05, -1.0, 1.0)
        self._mark(state, "correction")

    def on_send_failure(self, chat_key: str) -> None:
        state = self.get(chat_key)
        state.fatigue = _clamp(state.fatigue + 0.1, 0.0, 1.0)
        state.valence = _clamp(state.valence - 0.05, -1.0, 1.0)
        self._mark(state, "send_failure")

    def check_wait_timeout(self, chat_key: str, now: Optional[float] = None) -> Optional[str]:
        """等待超时检查（Phase 4）。返回 ``timeout`` / ``cooldown`` / None。

        超时后的 drop/follow_up/topic_change 由调用方决定；本层默认 drop，
        连续 3 次无人回应进入冷却。
        """

        now = time.monotonic() if now is None else now
        state = self.get(chat_key, now)
        if not state.wait.active():
            return None
        if now - state.wait.started_mono < state.wait.max_wait_seconds:
            return None
        state.wait = WaitExpectation()
        state.unanswered_count += 1
        state.valence = _clamp(state.valence - 0.05, -1.0, 1.0)
        if state.unanswered_count >= WAIT_COOLDOWN_AFTER_UNANSWERED:
            state.cooldown_until_mono = now + WAIT_COOLDOWN_SECONDS
            state.unanswered_count = 0
            self._mark(state, "unanswered_cooldown")
            return "cooldown"
        self._mark(state, "wait_timeout")
        return "timeout"

    def reset_rapport(self, chat_key: str) -> None:
        state = self.get(chat_key)
        state.rapport.clear()
        state.rapport_updated.clear()
        self._mark(state, "rapport_reset")

    def _bump_rapport(self, state: ChatState, user_id: str, delta: float) -> None:
        if not user_id:
            return
        state.rapport[user_id] = _clamp(state.rapport.get(user_id, 0.0) + delta, -1.0, 1.0)
        state.rapport_updated[user_id] = datetime.now(CN_TZ).isoformat(timespec="seconds")
        # 限制规模：只保留绝对值最大的 200 人。
        if len(state.rapport) > 200:
            keep = sorted(state.rapport, key=lambda k: abs(state.rapport[k]), reverse=True)[:200]
            state.rapport = {k: state.rapport[k] for k in keep}
            state.rapport_updated = {k: state.rapport_updated.get(k, "") for k in keep}

    # ---- 输出（Phase 3.2） ----
    def speak_components(
        self,
        chat_key: str,
        *,
        user_ids: list,
        directed_at_us: bool,
        now: Optional[float] = None,
    ) -> Dict[str, int]:
        """返回有界加性分量（整数），合计被裁剪到 ±STATE_SCORE_CAP。"""

        now = time.monotonic() if now is None else now
        state = self.get(chat_key, now)
        rapport_vals = [state.rapport.get(str(uid), 0.0) for uid in user_ids if uid]
        rapport = max(rapport_vals, key=abs) if rapport_vals else 0.0
        parts = {
            "rapport": int(round(10 * rapport)),
            "stimulus": int(round(8 * state.stimulus)),
            "flow": int(round(10 * state.flow)),
            # post_reply_boost 只在对方仍在和我们说话时生效，避免自言自语刷屏。
            "post_reply": int(round(10 * state.post_reply)) if directed_at_us else 0,
            "fatigue": -int(round(15 * state.fatigue)),
            "cooldown": -STATE_SCORE_CAP if (now < state.cooldown_until_mono and not directed_at_us) else 0,
        }
        total = sum(parts.values())
        # 正向只给小幅推动：2026-10-04 实测频率偏高，状态模型不应把
        # 本该等待的轮次推过阈值。未被点名时正向上限 5，被点名时 10。
        positive_cap = 10 if directed_at_us else 5
        if total > positive_cap:
            parts["cap"] = positive_cap - total
        elif total < -STATE_SCORE_CAP:
            parts["cap"] = -STATE_SCORE_CAP - total
        return parts

    def mood_hint(self, chat_key: str) -> str:
        """给 prompt 的一行辅助信息（不决定内容）。空串表示无需提示。"""

        state = self.get(chat_key)
        hints = []
        if state.fatigue > 0.6:
            hints.append("有点聊累了，话可以更少")
        if state.valence < -0.3:
            hints.append("刚被冷落或怼过，别硬凑热闹")
        elif state.valence > 0.4 and state.flow > 0.4:
            hints.append("聊得挺投入")
        return "；".join(hints)

    def snapshot(self, chat_key: str) -> dict:
        state = self.get(chat_key)
        data = asdict(state)
        data["rapport_top"] = sorted(state.rapport.items(), key=lambda kv: -abs(kv[1]))[:10]
        data.pop("rapport", None)
        return data


_STORE: Optional[ChatStateStore] = None


def get_state_store() -> ChatStateStore:
    """全局单例（数据目录 data/maisaka_state/chat_state.json）。"""

    global _STORE
    if _STORE is None:
        root = Path(__file__).resolve().parents[3] / "data" / "maisaka_state"
        _STORE = ChatStateStore(root / "chat_state.json")
    return _STORE
