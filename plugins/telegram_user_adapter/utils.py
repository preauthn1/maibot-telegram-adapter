"""Telegram 真人账号适配器工具函数。"""

from typing import Optional, Tuple

import base64

_TOPIC_GROUP_SPLITTER = "::tg-topic::"

# 打字速度兜底值，避免配置为 0 时除零。
DEFAULT_SAFE_CPS = 6.0


def to_base64(data: bytes) -> str:
    """将二进制数据编码为 base64 字符串。

    Args:
        data: 原始二进制数据。

    Returns:
        str: base64 字符串。
    """

    return base64.b64encode(data).decode("utf-8")


def pick_username(first_name: Optional[str], last_name: Optional[str], username: Optional[str]) -> str:
    """从 Telegram 用户字段中挑选一个展示名。

    Args:
        first_name: 名。
        last_name: 姓。
        username: @用户名。

    Returns:
        str: 展示名；全部缺失时返回占位名。
    """

    if username:
        return username
    name = (first_name or "") + (f" {last_name}" if last_name else "")
    return name.strip() or "TG用户"


def build_topic_group_id(
    chat_id: int | str,
    message_thread_id: Optional[int] = None,
) -> str:
    """生成用于会话分流的虚拟 group_id。

    话题群（forum）中每个 topic 需要独立会话，因此把 topic id 编码进 group_id。

    Args:
        chat_id: Telegram 聊天 ID。
        message_thread_id: 话题线程 ID。

    Returns:
        str: 虚拟 group_id。
    """

    base_chat_id = str(chat_id)
    if message_thread_id is None:
        return base_chat_id
    return f"{base_chat_id}{_TOPIC_GROUP_SPLITTER}mt={message_thread_id}"


def parse_topic_group_id(group_id: int | str) -> Tuple[str, Optional[int]]:
    """解析虚拟 group_id。

    Args:
        group_id: 由 :func:`build_topic_group_id` 生成的虚拟 group_id。

    Returns:
        Tuple[str, Optional[int]]: ``(raw_chat_id, message_thread_id)``。
    """

    raw_group_id = str(group_id)
    if _TOPIC_GROUP_SPLITTER not in raw_group_id:
        return raw_group_id, None

    base_chat_id, topic_payload = raw_group_id.split(_TOPIC_GROUP_SPLITTER, 1)
    message_thread_id: Optional[int] = None
    for part in topic_payload.split("&"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key != "mt":
            continue
        try:
            message_thread_id = int(value)
        except (TypeError, ValueError):
            continue
    return base_chat_id, message_thread_id


def chat_id_aliases(chat_id: str) -> set[str]:
    """生成 Telegram chat_id 的等价写法集合。

    Telegram 的超级群同时存在 ``-100xxxx``、``100xxxx``、``xxxx`` 三种写法，
    名单匹配时需要一并考虑。

    Args:
        chat_id: 原始 chat_id 字符串。

    Returns:
        set[str]: 等价 ID 集合。
    """

    normalized = str(chat_id or "").strip()
    if not normalized:
        return set()

    aliases = {normalized}
    signless = normalized[1:] if normalized.startswith("-") else normalized
    if signless:
        aliases.add(signless)
    if signless.startswith("100") and len(signless) > 3:
        aliases.add(signless[3:])
        aliases.add(f"-100{signless[3:]}")
    elif signless.isdigit():
        aliases.add(f"-100{signless}")
        aliases.add(f"100{signless}")
    return aliases


def estimate_typing_seconds(
    text_length: int,
    chars_per_second: float,
    min_delay: float,
    max_delay: float,
) -> float:
    """根据文本长度估算拟人化打字耗时。

    Args:
        text_length: 待发送文本长度。
        chars_per_second: 每秒键入字符数。
        min_delay: 最小停顿（模拟看到消息后的思考时间）。
        max_delay: 打字耗时上限。

    Returns:
        float: 建议的等待秒数。
    """

    safe_cps = chars_per_second if chars_per_second > 0 else DEFAULT_SAFE_CPS
    typing_cost = max(0, text_length) / safe_cps
    return max(min_delay, min(min_delay + typing_cost, max_delay))
