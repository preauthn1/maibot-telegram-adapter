"""上下文机器人消息过滤测试。

需求：上下文中不能包含机器人的消息（入群验证等）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pytest

from src.services.message_service import _is_bot_message


@dataclass
class _UserInfo:
    user_id: str = "1"
    user_nickname: str = "某人"
    user_cardname: Optional[str] = None
    is_bot: bool = False


@dataclass
class _MsgInfo:
    user_info: _UserInfo


@dataclass
class _Msg:
    processed_plain_text: str = ""
    nickname: str = "某人"
    is_bot: bool = False
    message_info: _MsgInfo = field(init=False)
    timestamp: datetime = field(default_factory=lambda: datetime(2026, 8, 31))

    def __post_init__(self) -> None:
        self.message_info = _MsgInfo(
            _UserInfo(user_nickname=self.nickname, is_bot=self.is_bot)
        )


def test_explicit_bot_flag_is_filtered() -> None:
    """适配器标记为 bot 的发送者应被过滤。"""

    assert _is_bot_message(_Msg("随便什么内容", is_bot=True))


def test_bot_username_suffix_is_filtered() -> None:
    """用户名以 bot 结尾是 Telegram 的硬性约定。

    真实样本：该群内有 @nmnmfunbot、@CM_Unban_bot 两个机器人。
    """

    assert _is_bot_message(_Msg("你好", nickname="CM_Unban_bot"))
    assert _is_bot_message(_Msg("你好", nickname="nmnmfunbot"))


@pytest.mark.parametrize(
    "nickname",
    ["nmBot", "自助解封机器人🚑", "CM_Unban_bot", "小助手Bot ", "验证机器人", "NMBOT"],
)
def test_real_bot_display_names_are_filtered(nickname: str) -> None:
    """真实机器人显示名应被过滤。

    显示名不受 username 规则约束，实测该群里有 "nmBot"、
    "自助解封机器人🚑" 这类带 emoji 或中文的名字。
    """

    assert _is_bot_message(_Msg("欢迎加入", nickname=nickname)), f"未过滤: {nickname!r}"


@pytest.mark.parametrize(
    "text",
    [
        "点击下方按钮完成验证",
        "入群验证已开启",
        "验证成功，欢迎加入",
        "请在 60 秒内完成验证",
        "您已被禁言 10 分钟",
        "已被管理员移除",
        "欢迎新朋友加入本群",
        "该消息含违规内容",
        "广告已拦截",
    ],
)
def test_system_notice_text_is_filtered(text: str) -> None:
    """系统通知类文本应被过滤，即使发送者未标记为 bot。

    这类文本含"点击下方按钮"等指令性内容，喂给模型会污染上下文。
    """

    assert _is_bot_message(_Msg(text)), f"未过滤: {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "今天全红，有和我一样的吗",
        "域名挂了换一个二级",
        "节点已更新",
        "我用的ccwu正常",
        "睡觉了",
        "晚安",
        "服了，死开子越来越多了",
        "app终于是整差不多了",
        "电信网吗？",
        "这个机器人挺好用的",
        "我在写一个 bot",
    ],
)
def test_real_human_messages_are_kept(text: str) -> None:
    """真人消息绝不能被误删。

    用例取自该群真实对话。误删会让上下文出现空洞，
    比保留个别机器人消息更糟。
    """

    assert not _is_bot_message(_Msg(text)), f"误判为机器人消息: {text!r}"


def test_empty_text_is_not_bot() -> None:
    """空正文（纯媒体）不应被判为机器人消息。"""

    assert not _is_bot_message(_Msg(""))


def test_nickname_containing_bot_but_not_suffix_is_kept() -> None:
    """昵称里含 bot 但不以其结尾的真人不应被误删。"""

    assert not _is_bot_message(_Msg("你好", nickname="botanist"))
    assert not _is_bot_message(_Msg("你好", nickname="机器人爱好者"))
