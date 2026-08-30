"""自我改进机制。

需求 7 要求把经验写入 SKILL.md / SOUL.md。这两个文件名是用户杜撰的，
本模块按实际语义落成两份 Markdown：

- ``SOUL.md``：**身份与性格**。相对稳定，描述"我是谁"——说话习惯、
  常用词、态度倾向。变化慢，改动需要更多证据。
- ``SKILL.md``：**聊天经验**。记录"什么场合怎么说效果好"——哪些回复
  被人接话了、哪些被冷场、哪些引起了怀疑。变化快。

两份文件都是人类可读可编辑的 Markdown，同时被程序解析回注到 prompt。

改进信号来自可观测的行为，而不是让模型自评：
- **被接话**：发言后 N 秒内有人回复 → 正向；
- **冷场**：发言后长时间无人理 → 负向；
- **被质疑**：对方消息命中"你是不是机器人/AI/bot"等特征 → 强负向，
  同时记录当时说了什么，便于人工排查。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import asyncio
import json
import re

_CN_TZ = timezone(timedelta(hours=8))

# 对方怀疑我们是机器人的特征词。命中即为强负向信号。
_SUSPICION_PATTERNS = (
    r"你是(?:不是)?(?:个)?(?:机器人|AI|ai|bot|Bot|人机|真人)",
    r"(?:是不是|难道是|该不会是)(?:机器人|AI|ai|bot|人机)",
    r"这(?:是|不是)(?:个)?(?:机器人|AI|ai|bot|人机)(?:吧|吗|么)",
    r"(?:机器人|AI|ai|bot|人机)(?:吧|吗|么)[？?]",
    r"(?:你|它|他|她)(?:说话|回复|聊天)(?:好|很|真)?(?:像|似)(?:个)?(?:机器人|AI|ai)",
    r"图灵测试",
    r"复读机",
    r"(?:自动)?(?:回复|发言)(?:机|脚本|程序)",
    # 最短形式的质疑：单独一个 "ai?" / "bot?" / "机器人?"。
    # 线上真实翻车样本就是一句 "ai？" —— 原有规则要求前后文，全部漏掉。
    r"^\s*(?:ai|bot|gpt|人机|机器人)\s*[?？]+\s*$",
    r"^\s*(?:ai|bot|gpt|人机|机器人)\s*[吧吗么]\s*[?？]*\s*$",
    r"(?:是|像)(?:个)?(?:ai|bot|gpt)(?:\b|吧|吗|么|$)",
    r"(?:机器人|人机)(?:吧|吗|么|哦|啊)?$",
    r"(?:chatgpt|大模型|语言模型|prompt)",
    r"(?:回复|说话)(?:太|好|真)?(?:快|标准|规整)",
)

# 大小写不敏感：线上真实样本里 "AI?" 与 "ai？" 都出现过。
_COMPILED_SUSPICION = tuple(re.compile(p, re.IGNORECASE) for p in _SUSPICION_PATTERNS)

_SOUL_HEADER = """# SOUL.md — 我是谁

这份文件描述本账号的身份与说话习惯。它变化很慢，是长期人格的沉淀。
你可以直接手工编辑本文件，程序会在下次启动时读取。

"""

_SKILL_HEADER = """# SKILL.md — 聊天经验

这份文件记录"什么场合怎么说效果好"，由程序根据实际反馈自动累积。
标记为 ⚠️ 的条目是被人怀疑过的表达，应当避免。

"""


def detect_suspicion(text: str) -> bool:
    """检测对方消息是否在怀疑我们不是真人。

    Args:
        text: 对方消息文本。

    Returns:
        bool: 命中怀疑特征时返回 ``True``。
    """

    normalized = (text or "").strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _COMPILED_SUSPICION)


# 出站自省：我们**自己**说出口的话里不该出现的东西。
# 这与 content_safety 的入站过滤是两回事——入站拦别人发来的脏东西，
# 这里拦的是\"我被带偏了/我怼人了\"，属于事后自省，用于沉淀教训。
_SELF_AGGRESSIVE: Tuple[str, ...] = (
    "sb", "傻逼", "煞笔", "你妈", "滚", "蠢货", "闭嘴",
    "智障", "弱智", "废物", "神经病", "有病吧", "垃圾",
    "急了", "破防", "你才",
)

# 顺着 NSFW 话题接话的迹象。真人会岔开或不接，机器人容易被带跑。
_SELF_NSFW_FOLLOWUP: Tuple[str, ...] = (
    "裸", "脱光", "开房", "约炮", "一夜情", "色情", "黄片",
)


def inspect_own_message(text: str) -> Tuple[str, List[str]]:
    """自省一条**我们自己发出**的消息是否越界。

    人设改了不代表模型永远守规矩；把越界的话记下来，
    才能在 prompt 经验里回灌\"这句翻过车\"，形成闭环。

    Args:
        text: 我们发出的文本。

    Returns:
        Tuple[str, List[str]]: ``(问题类型, 命中词列表)``。
            问题类型为空串表示没发现问题。
    """

    normalized = (text or "").strip().lower()
    if not normalized:
        return "", []

    aggressive = [w for w in _SELF_AGGRESSIVE if w in normalized]
    if aggressive:
        return "aggressive", aggressive

    nsfw = [w for w in _SELF_NSFW_FOLLOWUP if w in normalized]
    if nsfw:
        return "nsfw_followup", nsfw

    return "", []


@dataclass
class ChatOutcome:
    """一次发言的效果反馈。"""

    chat_id: str
    """所在聊天。"""

    text: str
    """我们发出的内容。"""

    got_reply: bool = False
    """是否有人接话。"""

    suspected: bool = False
    """是否被怀疑是机器人。"""

    suspicion_text: str = ""
    """触发怀疑的对方原话。"""

    violation_kind: str = ""
    """自省发现的问题类型，例如 ``aggressive`` / ``nsfw_followup``。空串表示没问题。"""

    violation_hits: List[str] = field(default_factory=list)
    """触发自省的具体命中词，仅用于本地复盘，绝不回显到聊天。"""


class SelfImprovementStore:
    """维护 SOUL.md / SKILL.md 与结构化经验数据。"""

    def __init__(self, base_dir: Path, logger: Any, *, enabled: bool = True) -> None:
        """初始化自我改进存储。

        Args:
            base_dir: 存放目录。
            logger: 插件日志器。
            enabled: 是否启用。
        """

        self._base_dir = base_dir
        self._logger = logger
        self._enabled = enabled
        self._soul_path = base_dir / "SOUL.md"
        self._skill_path = base_dir / "SKILL.md"
        self._state_path = base_dir / "self_improvement_state.json"
        self._lock = asyncio.Lock()
        self._state: Dict[str, Any] = {
            "total_messages": 0,
            "got_reply": 0,
            "ignored": 0,
            "suspected": 0,
            "suspicion_samples": [],
            "avoid_phrases": [],
        }

        if not self._enabled:
            return

        try:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            self._load_state()
            self._ensure_files()
        except OSError as exc:
            self._logger.warning(f"初始化自我改进存储失败 {self._base_dir}: {exc}")
            self._enabled = False

    @property
    def enabled(self) -> bool:
        """返回是否启用。

        Returns:
            bool: 启用返回 ``True``。
        """

        return self._enabled

    @property
    def soul_path(self) -> Path:
        """SOUL.md 路径。

        Returns:
            Path: 文件路径。
        """

        return self._soul_path

    @property
    def skill_path(self) -> Path:
        """SKILL.md 路径。

        Returns:
            Path: 文件路径。
        """

        return self._skill_path

    def _load_state(self) -> None:
        """从磁盘加载统计状态。"""

        if not self._state_path.exists():
            return
        try:
            loaded = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._logger.warning(f"读取自我改进状态失败，使用默认值: {exc}")
            return
        if isinstance(loaded, dict):
            self._state.update(loaded)

    def _save_state(self) -> None:
        """把统计状态写回磁盘。"""

        try:
            self._state_path.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            self._logger.warning(f"保存自我改进状态失败: {exc}")

    def _ensure_files(self) -> None:
        """首次运行时创建 SOUL.md / SKILL.md 骨架。"""

        if not self._soul_path.exists():
            self._soul_path.write_text(
                _SOUL_HEADER
                + "## 说话习惯\n\n"
                "- 句子短，很少用句号收尾\n"
                "- 不用书面语连接词（此外、然而、综上所述）\n"
                "- 一次只说一件事，不逐条回应对方的每个点\n\n"
                "## 态度\n\n"
                "- 不知道就说不知道，不编\n"
                "- 不主动提供帮助，不问\"还有什么需要\"\n\n",
                encoding="utf-8",
            )

        if not self._skill_path.exists():
            self._skill_path.write_text(
                _SKILL_HEADER + "## 有效表达\n\n（暂无，等待积累）\n\n## ⚠️ 应避免的表达\n\n（暂无）\n\n",
                encoding="utf-8",
            )

    async def record_outcome(self, outcome: ChatOutcome) -> None:
        """记录一次发言的效果。

        Args:
            outcome: 发言反馈。
        """

        if not self._enabled:
            return

        async with self._lock:
            self._state["total_messages"] = int(self._state.get("total_messages", 0)) + 1

            if outcome.violation_kind:
                # 自省命中：这是最该记住的一类教训——不是\"别人怀疑我\"，
                # 而是\"我自己说错了\"。计数、留样本，并写进要避免的表达。
                key = f"violation_{outcome.violation_kind}"
                self._state[key] = int(self._state.get(key, 0)) + 1

                violations: List[Dict[str, str]] = list(self._state.get("violation_samples", []))
                violations.append(
                    {
                        "ts": datetime.now(_CN_TZ).isoformat(),
                        "chat_id": outcome.chat_id,
                        "kind": outcome.violation_kind,
                        "our_text": outcome.text[:200],
                        "hits": ",".join(outcome.violation_hits[:5]),
                    }
                )
                self._state["violation_samples"] = violations[-50:]

                avoid_v: List[str] = list(self._state.get("avoid_phrases", []))
                snippet_v = outcome.text.strip()[:60]
                if snippet_v and snippet_v not in avoid_v:
                    avoid_v.append(snippet_v)
                self._state["avoid_phrases"] = avoid_v[-30:]

                self._logger.warning(
                    f"⚠️ 自省发现越界发言 kind={outcome.violation_kind} "
                    f"chat_id={outcome.chat_id} 内容={outcome.text[:60]!r}"
                )

            if outcome.suspected:
                self._state["suspected"] = int(self._state.get("suspected", 0)) + 1
                samples: List[Dict[str, str]] = list(self._state.get("suspicion_samples", []))
                samples.append(
                    {
                        "ts": datetime.now(_CN_TZ).isoformat(),
                        "chat_id": outcome.chat_id,
                        "our_text": outcome.text[:200],
                        "their_text": outcome.suspicion_text[:200],
                    }
                )
                self._state["suspicion_samples"] = samples[-50:]

                avoid: List[str] = list(self._state.get("avoid_phrases", []))
                snippet = outcome.text.strip()[:60]
                if snippet and snippet not in avoid:
                    avoid.append(snippet)
                self._state["avoid_phrases"] = avoid[-30:]

                self._logger.warning(
                    f"⚠️ 有人怀疑我们不是真人 chat_id={outcome.chat_id} "
                    f"对方说={outcome.suspicion_text[:60]!r} 我们上一句={outcome.text[:60]!r}"
                )
            elif outcome.got_reply:
                self._state["got_reply"] = int(self._state.get("got_reply", 0)) + 1
            else:
                self._state["ignored"] = int(self._state.get("ignored", 0)) + 1

            self._save_state()
            self._rewrite_skill_file()
            self._write_prompt_experience()

    def _write_prompt_experience(self) -> None:
        """把经验导出为主程序可读的 prompt 片段。

        主程序运行在另一个进程，无法直接调用本类，因此通过磁盘上的
        约定文件名 ``prompt_experience.txt`` 传递。
        """

        block = self.build_prompt_block()
        try:
            (self._base_dir / "prompt_experience.txt").write_text(block, encoding="utf-8")
        except OSError as exc:
            self._logger.warning(f"写入 prompt 经验文件失败: {exc}")

    def _rewrite_skill_file(self) -> None:
        """根据当前统计重写 SKILL.md。"""

        total = int(self._state.get("total_messages", 0))
        got_reply = int(self._state.get("got_reply", 0))
        ignored = int(self._state.get("ignored", 0))
        suspected = int(self._state.get("suspected", 0))
        reply_rate = (got_reply / total * 100) if total else 0.0
        suspicion_rate = (suspected / total * 100) if total else 0.0

        lines = [
            _SKILL_HEADER,
            "## 统计\n",
            f"- 累计发言：{total}",
            f"- 有人接话：{got_reply}（{reply_rate:.1f}%）",
            f"- 无人理会：{ignored}",
            f"- 被怀疑是机器人：{suspected}（{suspicion_rate:.1f}%）",
            "",
            "## ⚠️ 应避免的表达\n",
        ]

        avoid = list(self._state.get("avoid_phrases", []))
        if avoid:
            lines.append("以下表达出现后曾被人怀疑不是真人，尽量别再这么说：\n")
            lines.extend(f"- {phrase}" for phrase in avoid[-15:])
        else:
            lines.append("（暂无）")

        lines.append("\n## 被怀疑的场景记录\n")
        samples = list(self._state.get("suspicion_samples", []))
        if samples:
            for sample in samples[-10:]:
                lines.append(
                    f"- `{sample.get('ts', '')}` 群 `{sample.get('chat_id', '')}`：\n"
                    f"  - 我们说：{sample.get('our_text', '')}\n"
                    f"  - 对方回：{sample.get('their_text', '')}"
                )
        else:
            lines.append("（暂无）")

        lines.append("")

        try:
            self._skill_path.write_text("\n".join(lines), encoding="utf-8")
        except OSError as exc:
            self._logger.warning(f"写入 SKILL.md 失败: {exc}")

    def build_prompt_block(self, max_chars: int = 800) -> str:
        """把经验汇总成可注入 prompt 的文本块。

        Args:
            max_chars: 返回文本的长度上限。

        Returns:
            str: prompt 片段；无内容时返回空串。
        """

        if not self._enabled:
            return ""

        sections: List[str] = []

        soul_text = self._safe_read(self._soul_path)
        if soul_text:
            sections.append(f"【我的说话习惯】\n{soul_text}")

        avoid = list(self._state.get("avoid_phrases", []))
        if avoid:
            avoid_lines = "\n".join(f"- {phrase}" for phrase in avoid[-8:])
            sections.append(
                "【以下表达曾被人怀疑不是真人，绝对不要再这么说】\n" + avoid_lines
            )

        # 自省教训单独成段：这些不是\"像不像真人\"的问题，而是\"说错话\"的问题，
        # 混在一起会稀释警示强度。
        violations = list(self._state.get("violation_samples", []))
        if violations:
            recent = violations[-5:]
            aggressive = [v for v in recent if v.get("kind") == "aggressive"]
            nsfw = [v for v in recent if v.get("kind") == "nsfw_followup"]

            lines: List[str] = []
            if aggressive:
                lines.append("你曾经说过这些带攻击性的话，翻过车，不要再犯：")
                lines.extend(f"- {v.get('our_text', '')[:50]}" for v in aggressive)
            if nsfw:
                lines.append("你曾经顺着下流话题接话，这是被带偏了。遇到这类内容要岔开或不接：")
                lines.extend(f"- {v.get('our_text', '')[:50]}" for v in nsfw)
            if lines:
                sections.append("【我犯过的错】\n" + "\n".join(lines))

        if not sections:
            return ""

        block = "\n\n".join(sections)
        return block[:max_chars]

    def _safe_read(self, path: Path) -> str:
        """安全读取文本文件，去掉标题与文件自身的说明文字。

        说明文字（"这份文件…""你可以直接手工编辑…"）是写给人看的，
        绝不能混进 prompt，否则会污染模型的人设理解。

        Args:
            path: 文件路径。

        Returns:
            str: 文件正文；读取失败时返回空串。
        """

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return ""

        body_lines: List[str] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # 过滤面向人类读者的元说明。
            if stripped.startswith(("这份文件", "你可以直接手工编辑", "标记为")):
                continue
            body_lines.append(stripped)
        return "\n".join(body_lines).strip()

    def get_stats(self) -> Dict[str, Any]:
        """返回当前统计快照。

        Returns:
            Dict[str, Any]: 统计数据副本。
        """

        return dict(self._state)
