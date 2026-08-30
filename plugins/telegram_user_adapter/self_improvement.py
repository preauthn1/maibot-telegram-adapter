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

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
)

_COMPILED_SUSPICION = tuple(re.compile(p) for p in _SUSPICION_PATTERNS)

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
