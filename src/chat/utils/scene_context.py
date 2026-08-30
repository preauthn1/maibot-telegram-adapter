"""会话场景上下文。

问题：模型不知道自己在哪、在跟谁说话。实测中它在**私聊**里回答
"麦麦啊，群里的人" —— 私聊根本没有群，这是明显的破绽。

原因：人设 prompt 只描述"你是谁"，不描述"你现在在什么平台、
什么场合、对面是谁"。模型只能靠猜，猜错就穿帮。

本模块从 ``chat_stream`` 生成一段**场景说明**：当前平台、私聊还是群聊、
对方是谁 / 群名是什么。以及适配器写出的账号资料（用户名等）。

这是**事实陈述**而非行为指令，因此放在身份铁律之前，
避免冲淡铁律的优先级。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import json
import time

# 适配器把当前账号资料写到 data/plugins/<插件ID>/ 下的这个文件。
_PROFILE_FILE_NAME = "account_profile.json"

_CACHE_TTL_SECONDS = 60.0
_profile_cache: Dict[str, Any] = {}
_profile_cache_at: float = 0.0

# 平台标识 -> 展示名。用户看到的是"Telegram"而不是"telegram"。
_PLATFORM_DISPLAY = {
    "telegram": "Telegram",
    "qq": "QQ",
    "wechat": "微信",
    "weixin": "微信",
    "discord": "Discord",
    "feishu": "飞书",
    "lark": "飞书",
}


def _load_account_profile() -> Dict[str, Any]:
    """读取适配器写出的账号资料。

    Returns:
        Dict[str, Any]: 账号资料；未找到或读取失败时返回空字典。
    """

    global _profile_cache, _profile_cache_at

    now = time.monotonic()
    if _profile_cache and (now - _profile_cache_at) < _CACHE_TTL_SECONDS:
        return _profile_cache

    plugin_root = Path("data") / "plugins"
    if not plugin_root.is_dir():
        _profile_cache_at = now
        return {}

    for candidate in sorted(plugin_root.glob(f"*/{_PROFILE_FILE_NAME}")):
        try:
            loaded = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(loaded, dict):
            _profile_cache = loaded
            _profile_cache_at = now
            return loaded

    _profile_cache_at = now
    return {}


def build_scene_context_block(chat_stream: Optional[Any]) -> str:
    """根据当前会话构建场景说明。

    Args:
        chat_stream: 当前 ``BotChatSession``；为 ``None`` 时返回空串。

    Returns:
        str: 可拼进 system prompt 的中文场景说明；信息不足时返回空串。
    """

    if chat_stream is None:
        return ""

    platform = (chat_stream.platform or "").strip().lower()
    if not platform:
        return ""

    platform_name = _PLATFORM_DISPLAY.get(platform, platform)
    profile = _load_account_profile()

    lines = ["【当前场景 · 事实，不是设定】"]

    # 自己的账号资料：让它知道别人看到的自己长什么样。
    identity_bits = []
    display_name = profile.get("display_name")
    username = profile.get("username")
    if display_name:
        identity_bits.append(f"显示名是「{display_name}」")
    if username:
        identity_bits.append(f"用户名是 @{username}")

    if identity_bits and profile.get("platform", platform) == platform:
        lines.append(f"你正在用{platform_name}，你的账号{'，'.join(identity_bits)}。")
    else:
        lines.append(f"你正在用{platform_name}。")

    group_id = chat_stream.group_id
    if group_id:
        group_name = chat_stream.group_name
        where = f"群「{group_name}」" if group_name else "一个群"
        lines.append(f"现在是**群聊**，你在{where}里。")
        lines.append("群里有别人，不是每条消息都在跟你说话。")
    else:
        peer = chat_stream.user_nickname
        who = f"「{peer}」" if peer else "对方"
        lines.append(
            f"现在是**一对一私聊**，只有你和{who}两个人。这里没有群，也没有其他人在看。"
        )
        # 这条是实测中真实踩过的坑：私聊里自称"群里的人"。
        lines.append('不要说"群里""大家""你们"，不要把这里当成群聊。')

    lines.append(
        "不确定对方是谁、你们怎么认识的时候，就含糊带过或者反问，不要编造你们的关系和共同经历。"
    )

    return "\n".join(lines)
