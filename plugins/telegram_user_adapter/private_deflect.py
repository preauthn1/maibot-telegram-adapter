"""陌生私聊防护：将资源请求引导回公开群聊。

私聊与群聊的频率、权限和审计边界不同；对陌生请求只做一次简短引导，
不伪造账号状态，不泄露节点、订阅、密钥或其他私有资源。
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
