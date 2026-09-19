"""私聊挡人：用"被双向了发不了私信"当挡箭牌。

## 事故背景

2026-09-03 早上我们在群里耐心答疑（"按ASN推断"、"跳google.cn
就是出口被谷歌判成大陆了 ws和xhttp命中的cf边缘不一样"），
一个自称"纯新手"的成员至少 3 次直接回复我们请教，
当晚 22:27 转为私聊要资源。

最讽刺的是我们自己 10:42 在群里说过：

    "这种上赶着要的我怀疑是收号的"
    "谁知道他要节点干麻 万一拿去干坏事查到你不就麻烦了"

结果因为太热心，自己成了被要的那个。

## 为什么必须挡

1. **私聊比群聊危险得多**。群里可以装忙不回，几十条消息里
   漏掉一条毫无异常；私聊是一对一，不回就是明显异常，
   回则要维持长对话，暴露面成倍增加。
2. **群聊的节奏闸门在私聊里全部失效**——占比、连发抑制、
   人类作息都是按群设计的。
3. **陌生人索要节点/资源本身有安全风险**。

## 为什么用"被双向了"

这是 Telegram 真实存在的机制：开了双向机器人转发、
或隐私设置限制非联系人私信，都会导致对方发不进来。
群里技术人都懂这回事，比"我不想聊"自然得多，
也不会显得刻意回避某个人。

关键是**只回一次**。每条私聊都回"发不了私信"，
本身就是最明显的机器人行为。
"""

from typing import Optional, Sequence, Set, Tuple

import random

# 挡箭牌话术池。
#
# 设计约束（见配套测试）：
#   - 必须提到私信/双向限制，给出可信理由
#   - 不道歉（真人不会为发不了私信道歉）
#   - 短（群里真人发言中位 14 字）
#   - 多条随机，固定一句是脚本特征
DEFLECT_REPLIES: Tuple[str, ...] = (
    "这里不处理陌生私聊，有事请在群里说",
    "私聊不处理，有事群里说吧",
    "请在群里交流，这里不接私信",
)


def should_deflect_private(
    *,
    sender_id: str,
    whitelist: Set[str],
    already_deflected: Optional[Set[str]] = None,
) -> bool:
    """判断是否该对这次私聊发挡箭牌。

    Args:
        sender_id: 私聊发起者 ID；取不到时传空字符串。
        whitelist: 允许私聊的 ID 集合（自己人）。
        already_deflected: 已经挡过的 ID 集合；重复挡会露馅。

    Returns:
        bool: 应当发挡箭牌返回 ``True``；白名单或已挡过返回 ``False``。
    """

    if not sender_id:
        # 拿不到 ID 按陌生人处理——保守优先
        return True
    if sender_id in whitelist:
        return False
    if already_deflected and sender_id in already_deflected:
        # 已经说过发不了私信，再说就是机器人
        return False
    return True


def build_deflect_reply(pool: Optional[Sequence[str]] = None) -> str:
    """挑一条挡箭牌话术。

    Args:
        pool: 自定义话术池；``None`` 时用 :data:`DEFLECT_REPLIES`。

    Returns:
        str: 一条挡箭牌话术。
    """

    candidates = tuple(pool) if pool else DEFLECT_REPLIES
    return random.choice(candidates)
