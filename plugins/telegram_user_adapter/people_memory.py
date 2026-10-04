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
from pathlib import Path
from typing import Any, Dict, List, Optional

import json
import logging
import re
import time

# 每人最多记多少条事实。
#
# 8 条：够刻画一个群友的基本轮廓（职业、设备、地域、偏好），
# 又不至于让 prompt 里的人物信息挤掉当前对话。
DEFAULT_MAX_FACTS_PER_PERSON = 8

# 注入 prompt 的默认字符上限。
DEFAULT_PROMPT_MAX_CHARS = 300

# 自我陈述的开头。只有本人说自己的话才值得记。
#
# 为什么必须用白名单：原实现是黑名单（不含"正在""刚才"等词即算事实），
# 用封禁当天 60925 条真实入站消息端到端跑，判定 22% 是"稳定事实"，
# 记下 1071 人、605 KB，内容全是 URL、引用块、"哦哦"、"已销号"。
# 这些注入 prompt 只会污染上下文，比没有记忆更糟。
#
# 群聊里绝大多数话是在聊事、不是在自我介绍。真正值得记的是
# "我在深圳做前端"这类自述，占比很低——宁可少记也不能记错。
_SELF_STATEMENT_PREFIXES = (
    "我是",
    "我在",
    "我用",
    "我家",
    "我做",
    "我搞",
    "我平时",
    "我一般",
    "我们公司",
    "我公司",
    "我的",
    # 中文口语常省略主语："在用 OpenWrt""搞前端的""有台群晖"。
    # 这些同样是自述，只是把"我"省了。
    "在用",
    "在做",
    "在跑",
    "在写",
    "用的是",
    "搞",
    "做的是",
    "有台",
    "有个",
    "家里",
    "公司",
)

# "在<地点>" 型自述，如"在深圳做前端"。
#
# 不写死城市名：城市太多且会变。用「在 + 2-4 个汉字 + 动词」的
# 结构来认，比穷举地名更稳，也不会把"在群里说"这种话收进来。
_LOCATION_STATEMENT = re.compile(r"^在[\u4e00-\u9fff]{2,4}(?:做|干|搞|上班|工作|读)")

# 即使是自述，含这些也不收：URL、引用块、@提及都是转述或链接，
# 不是关于说话人自己的稳定属性。
_NON_FACT_SIGNALS = (
    "http://",
    "https://",
    "[回复",
    "[媒体]",
    "@",
)

# 自述的合理长度区间（字符）。
#
# 下限 3：真实自述可以很短——"在深圳""搞前端的""有台群晖"。
# 过滤噪音主要靠白名单前缀，不靠长度。
# 上限 40：更长的多半是在讲事情而不是自我介绍。
_FACT_MIN_CHARS = 3
_FACT_MAX_CHARS = 40

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
    "现在变",
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

    四道门槛，全部通过才收：

    1. **必须是第一人称自述**（白名单）。群聊里绝大多数话是在聊事，
       只有"我在深圳做前端"这类自我陈述才是关于说话人的稳定属性。
    2. **长度合理**。太短没信息量，太长多半在讲事情而非自我介绍。
    3. **不含 URL / 引用块 / @提及**。那些是转述或链接。
    4. **不是临时状态**。"我正在装系统"过几天就是错误信息。

    为什么门槛要这么严：原实现只有第 4 条（黑名单），用 60925 条
    真实入站消息端到端跑，22% 被判为"稳定事实"，记下 1071 人、
    605 KB 的 URL 和"哦哦"。注入 prompt 只会污染上下文。

    Args:
        text: 待判断的陈述。

    Returns:
        bool: 稳定事实返回 True；否则返回 False。
    """

    stripped = text.strip()
    if not stripped:
        return False

    if not (_FACT_MIN_CHARS <= len(stripped) <= _FACT_MAX_CHARS):
        return False

    if not (
        stripped.startswith(_SELF_STATEMENT_PREFIXES)
        or _LOCATION_STATEMENT.match(stripped)
    ):
        return False

    if any(signal in stripped for signal in _NON_FACT_SIGNALS):
        return False

    return not any(marker in stripped for marker in _VOLATILE_MARKERS)


class PeopleMemory:
    """按人存储稳定事实，容量受限、支持注入 prompt。"""

    def __init__(
        self,
        *,
        max_facts_per_person: int = DEFAULT_MAX_FACTS_PER_PERSON,
        storage_path: Optional[Path] = None,
        logger: Optional[Any] = None,
    ) -> None:
        """初始化人物记忆。

        Args:
            max_facts_per_person: 每人保留的事实条数上限。
            storage_path: 落盘路径；为 None 时退化为纯内存。
            logger: 日志器；未提供时用模块级 logger。
        """

        self.max_facts_per_person = max_facts_per_person
        self.storage_path = storage_path
        self._logger = logger or logging.getLogger(__name__)
        # person_id -> {事实文本: PersonFact}，用 OrderedDict 维持插入序以便淘汰
        self._facts: Dict[str, "OrderedDict[str, PersonFact]"] = {}

        if storage_path is not None:
            self._load()

    def _load(self) -> None:
        """从磁盘恢复记忆。

        记忆的价值在于跨会话——「这人搞前端」必须活过进程重启，
        否则每次重启都从零开始，等于没记。

        文件损坏时不让插件起不来：改名留证后以空记忆启动。
        人物记忆丢了是遗憾，账号因此下线才是事故。
        """

        path = self.storage_path
        if path is None or not path.exists():
            return

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            # 留证再走，方便事后排查是怎么坏的
            backup = path.with_suffix(f".json.corrupt-{int(time.time())}")
            try:
                path.rename(backup)
            except OSError:
                pass
            self._logger.warning(
                f"人物记忆文件损坏，已备份到 {backup.name} 并以空记忆启动: {exc}"
            )
            return

        if not isinstance(raw, dict):
            return

        for person_id, items in raw.items():
            if not isinstance(items, list):
                continue
            bucket: "OrderedDict[str, PersonFact]" = OrderedDict()
            for item in items:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text", "")).strip()
                if not text:
                    continue
                bucket[text] = PersonFact(
                    text=text,
                    created_at=float(item.get("created_at", 0.0)),
                )
            # 尊重当前容量上限：配置调小后不该把超出的旧事实读回来
            while len(bucket) > self.max_facts_per_person:
                bucket.popitem(last=False)
            if bucket:
                self._facts[str(person_id)] = bucket

    def save(self) -> None:
        """把记忆写回磁盘。

        用临时文件 + 原子替换：写一半断电会留下半个 JSON，
        下次启动就得走损坏分支，白丢全部记忆。

        未配置路径时为空操作，方便测试与纯内存场景。
        """

        path = self.storage_path
        if path is None:
            return

        payload = {
            person_id: [
                {"text": fact.text, "created_at": fact.created_at}
                for fact in bucket.values()
            ]
            for person_id, bucket in self._facts.items()
        }

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError as exc:
            self._logger.warning(f"人物记忆写入失败: {exc}")

    def remember(
        self, person_id: str, text: str, *, now: Optional[float] = None
    ) -> bool:
        """记录一条关于某人的事实。

        Args:
            person_id: 人物标识。
            text: 事实描述。
            now: 时间戳，便于测试注入。

        Returns:
            bool: **新增**了一条事实时返回 True；
                因是临时状态被拒、或该事实已知，均返回 False。

                注意"已知"也返回 False：调用方用这个返回值决定
                要不要落盘，若已知也算 True，群里反复出现同一句话
                就会不停触发写盘。
        """

        if not person_id or not text.strip():
            return False

        if not is_durable_fact(text):
            return False

        current = now if now is not None else time.time()
        bucket = self._facts.setdefault(person_id, OrderedDict())

        normalized = text.strip()
        if normalized in bucket:
            # 已知事实，不重复存储，也不算新增
            return False

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
