"""人设一致性防护：拦截与人设矛盾的个人身份自述。

真实事故（2026-09-02 23:00:39，某技术交流群）：

    22:58:12  Silas   （长篇吐槽老家高中的作息时间）
    23:00:02  Silas   看着真踏马窒息
    23:00:39  我们    我刚高中毕业没多久      ← 顺着话题即兴编的

人设是「大二女大学生」，说自己刚高中毕业差着一到两年。

为什么这条比普通的人设漂移严重得多：
这个群极度排斥「小孩哥」（未成年/学生党）。全天 467 条消息提到该词，
群里有 CM_Unban_bot 联网 ban 机制专门对付，还讨论过建 GitHub 名单
公示他们的 TG ID。典型态度：

    lrlbl      「冒充小孩哥」→「那更该骂了」
    wanjiu05   「傻逼小孩哥在我群里聊政治」
    RealNeoMan 「我是真能用的，不像小孩哥是盗图」

自称刚高中毕业 = 自报家门说自己是小孩哥，直接踩红线。
而我们此前还跟着骂过小孩哥（09-02 12:55「以后ban人理由一栏全写小孩哥」），
前后一对照就是现成的把柄。

设计要点：
只拦「第一人称自述」，不拦「讨论别人」。群里最热的话题就是骂小孩哥，
把这类发言一并拦掉会让 bot 在高频话题上突然失语，反而更可疑。
"""

from dataclasses import dataclass
from typing import Optional

import re

# 人设锚点：与 config/bot_config.toml 的 personality 对齐。
#
# 这里写死而不读配置，是因为读配置会引入插件对主程序配置的依赖，
# 而且人设一旦改动，本文件的正则也必须同步复核——写死能强制这个复核。
_PERSONA_TEXT = "大二女大学生（18-20 岁在读本科）"

# 第一人称标记：必须出现，否则视为在说别人。
_FIRST_PERSON = re.compile(r"(?:^|[，。！？、\s])我(?![们的])|^我")

# 与人设矛盾的身份自述。
#
# 未成年侧：群里的红线，命中即拦。
_UNDERAGE = re.compile(
    r"我(?:刚|才|正)?(?:上|读|念|在)?(?:高中|初中|小学|中学)(?:毕业|生|的时候)?"
    r"|我(?:高|初)[一二三]\b"
    r"|我今年(?:1[0-7]|[0-9])(?![0-9])"
    r"|我(?:还)?(?:在|是)?(?:上|读)(?:高|初)中"
    r"|我们学校(?=.*(?:早读|晚自习|班主任|开学|上课铃))"
)

# 超龄侧：自称已工作多年、研究生毕业等，同样与在读本科矛盾。
#
# 数量词要同时覆盖阿拉伯数字与中文数字：真人打字两种都用，
# 只认 \d+ 会漏掉"我工作十年了"这类最自然的说法。
_OVERAGE = re.compile(
    r"我(?:研究生|硕士|博士|本科)?毕业(?:好)?(?:几|\d+|[一二三四五六七八九十两])+年"
    r"|我今年(?:2[5-9]|[3-9][0-9])"
    r"|我工作(?:了)?(?:好)?(?:几|\d+|[一二三四五六七八九十两])+年"
    r"|我(?:上)?班(?:上)?了(?:好)?(?:几|\d+|[一二三四五六七八九十两])+年"
)


@dataclass(frozen=True)
class PersonaVerdict:
    """人设一致性检查结论。

    Attributes:
        allowed: 是否放行。
        reason: 拦截原因；放行时为 ``None``。
        matched: 命中的片段，便于日志定位。
    """

    allowed: bool
    reason: Optional[str] = None
    matched: Optional[str] = None


def describe_persona() -> str:
    """返回当前人设描述，供日志与告警使用。

    Returns:
        str: 人设文字描述。
    """

    return _PERSONA_TEXT


def check_persona_consistency(text: str) -> PersonaVerdict:
    """检查文本是否含与人设矛盾的身份自述。

    只在出现第一人称时判定，讨论他人不受影响。

    Args:
        text: 待发送文本。

    Returns:
        PersonaVerdict: 检查结论。
    """

    if not text or not text.strip():
        return PersonaVerdict(allowed=True)

    # 没有第一人称 = 在说别人，直接放行。
    # 群里最热的话题就是骂小孩哥，这类发言必须能正常参与。
    if not _FIRST_PERSON.search(text):
        return PersonaVerdict(allowed=True)

    hit = _UNDERAGE.search(text)
    if hit:
        return PersonaVerdict(
            allowed=False,
            reason=(
                f"自述未成年/中学生，与人设「{_PERSONA_TEXT}」矛盾；"
                f"该群极度排斥小孩哥，此类发言会直接踩红线"
            ),
            matched=hit.group(0),
        )

    hit = _OVERAGE.search(text)
    if hit:
        return PersonaVerdict(
            allowed=False,
            reason=f"自述年龄/资历远超人设「{_PERSONA_TEXT}」",
            matched=hit.group(0),
        )

    return PersonaVerdict(allowed=True)
