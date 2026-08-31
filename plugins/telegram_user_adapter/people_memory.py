"""人物记忆：记住群友的稳定事实。

为什么需要这个模块
------------------

借鉴 Hermes 的记忆分层。Hermes 把记忆分成两类：

- **durable facts**：跨会话持久的事实（偏好、环境、约定），
  每轮注入上下文，要求精炼高信号
- **会话状态**：任务进度、临时上下文，用完即弃

我们此前只有 ``SOUL.md``（我是谁）和 ``SKILL.md``（怎么说话），
**没有任何地方记"对方是谁"**。

这个缺失有实际后果：同一个人昨天说过在用 OpenWrt，今天再聊到
路由我们毫无印象，每次都像初次见面。真人不是这样——群友之间
会记得"这人搞前端"、"那位有台 NAS"。记忆缺失比偶尔说错话
更容易让人觉得不对劲，而账号已经因为被人识破举报而封过一次。

Hermes 的几条约束一并借鉴：

1. **只存稳定事实**。"他正在装系统"一周后就是噪音，
   "他用 Arch"才是可复用的。带进行时/临时性词汇的一律拒收。
2. **有容量上限**。记忆是每轮都要付出的上下文成本，
   不能无限膨胀，满了淘汰最旧的。
3. **声明式陈述**。存"他用 Arch"，不存"记得跟他聊 Arch"——
   后者会在下次被当成指令执行。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional

import time

# 每人最多记多少条事实。
#
# 8 条：够刻画一个群友的基本轮廓（职业、设备、地域、偏好），
# 又不至于让 prompt 里的人物信息挤掉当前对话。
DEFAULT_MAX_FACTS_PER_PERSON = 8

# 注入 prompt 的默认字符上限。
DEFAULT_PROMPT_MAX_CHARS = 300

# 临时状态特征词：命中则拒收。
#
# 这些词说明陈述的是"此刻在做什么"而非"是什么样的人"。
# 存进去过几天就是错误信息——比没有记忆更糟。
_VOLATILE_MARKERS = (
    "正在",
    "刚才",
    "刚刚",
    "马上",
    "等下",
    "待会",
    "今天在",
    "明天要",
    "现在在",
)


@dataclass(frozen=True)
class PersonFact:
    """关于某个人的一条稳定事实。

    Attributes:
        text: 事实描述。
        created_at: 记录时间戳。
    """

    text: str
    created_at: float


def is_durable_fact(text: str) -> bool:
    """判断一条陈述是否属于可长期保存的稳定事实。

    Args:
        text: 待判断的陈述。

    Returns:
        bool: 稳定事实返回 True；临时状态返回 False。
    """

    stripped = text.strip()
    if not stripped:
        return False
    return not any(marker in stripped for marker in _VOLATILE_MARKERS)


class PeopleMemory:
    """按人存储稳定事实，容量受限、支持注入 prompt。"""

    def __init__(
        self,
        *,
        max_facts_per_person: int = DEFAULT_MAX_FACTS_PER_PERSON,
    ) -> None:
        """初始化人物记忆。

        Args:
            max_facts_per_person: 每人保留的事实条数上限。
        """

        self.max_facts_per_person = max_facts_per_person
        # person_id -> {事实文本: PersonFact}，用 OrderedDict 维持插入序以便淘汰
        self._facts: Dict[str, "OrderedDict[str, PersonFact]"] = {}

    def remember(
        self, person_id: str, text: str, *, now: Optional[float] = None
    ) -> bool:
        """记录一条关于某人的事实。

        Args:
            person_id: 人物标识。
            text: 事实描述。
            now: 时间戳，便于测试注入。

        Returns:
            bool: 成功记录返回 True；因是临时状态而被拒返回 False。
        """

        if not person_id or not text.strip():
            return False

        if not is_durable_fact(text):
            return False

        current = now if now is not None else time.time()
        bucket = self._facts.setdefault(person_id, OrderedDict())

        normalized = text.strip()
        if normalized in bucket:
            # 已知事实，不重复存储
            return True

        bucket[normalized] = PersonFact(text=normalized, created_at=current)

        # 超容量则淘汰最旧的
        while len(bucket) > self.max_facts_per_person:
            bucket.popitem(last=False)

        return True

    def recall(self, person_id: str) -> List[PersonFact]:
        """取回关于某人的全部事实。

        Args:
            person_id: 人物标识。

        Returns:
            List[PersonFact]: 按记录顺序排列；未知的人返回空列表。
        """

        bucket = self._facts.get(person_id)
        if not bucket:
            return []
        return list(bucket.values())

    def build_prompt_block(
        self, person_id: str, max_chars: int = DEFAULT_PROMPT_MAX_CHARS
    ) -> str:
        """构造注入 prompt 的人物信息块。

        Args:
            person_id: 人物标识。
            max_chars: 字符上限。

        Returns:
            str: 人物信息文本；无记忆时返回空串。
        """

        facts = self.recall(person_id)
        if not facts:
            return ""

        lines: List[str] = []
        used = 0
        # 从最新往回取：越近的事实越可能与当前话题相关
        for fact in reversed(facts):
            line = f"- {fact.text}"
            if used + len(line) + 1 > max_chars:
                break
            lines.append(line)
            used += len(line) + 1

        return "\n".join(lines)

    def known_people(self) -> int:
        """返回已记录的人数。

        Returns:
            int: 人数。
        """

        return len(self._facts)
