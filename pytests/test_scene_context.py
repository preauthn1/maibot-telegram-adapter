"""会话场景上下文测试。

回归实测中的真实破绽：账号在**私聊**里回答"麦麦啊，群里的人"。
私聊没有群，这是明显的自动化特征。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import json

import pytest

from src.chat.utils import scene_context
from src.chat.utils.scene_context import build_scene_context_block


class _FakeChatStream:
    """最小化的 BotChatSession 替身。"""

    def __init__(
        self,
        platform: str = "telegram",
        group_id: Optional[str] = None,
        group_name: Optional[str] = None,
        user_nickname: Optional[str] = None,
    ) -> None:
        self.platform = platform
        self.group_id = group_id
        self.group_name = group_name
        self.user_nickname = user_nickname


@pytest.fixture(autouse=True)
def _clear_profile_cache() -> None:
    """每个用例前清掉账号资料缓存，避免相互污染。"""

    scene_context._profile_cache = {}
    scene_context._profile_cache_at = 0.0


def test_private_chat_forbids_group_wording() -> None:
    """私聊场景必须明确说明"这里没有群"。

    回归实测破绽：私聊里自称"群里的人"。
    """

    block = build_scene_context_block(_FakeChatStream(user_nickname="Poland Brown"))

    assert "私聊" in block
    assert "Poland Brown" in block
    assert "没有群" in block
    assert "群里" in block and "不要说" in block


def test_group_chat_states_group_name() -> None:
    """群聊场景应说明群名，且不应出现私聊措辞。"""

    stream = _FakeChatStream(group_id="-100123", group_name="测试群")
    block = build_scene_context_block(stream)

    assert "群聊" in block
    assert "测试群" in block
    assert "一对一私聊" not in block


def test_platform_name_is_humanized() -> None:
    """平台名应显示为 Telegram 而不是小写标识。"""

    block = build_scene_context_block(_FakeChatStream(platform="telegram"))

    assert "Telegram" in block


def test_unknown_platform_falls_back_to_raw_value() -> None:
    """未知平台不应崩溃，直接用原始标识。"""

    block = build_scene_context_block(_FakeChatStream(platform="matrix"))

    assert "matrix" in block


def test_none_chat_stream_returns_empty() -> None:
    """没有会话时返回空串，不注入任何内容。"""

    assert build_scene_context_block(None) == ""


def test_empty_platform_returns_empty() -> None:
    """平台缺失时信息不足，不编造场景。"""

    assert build_scene_context_block(_FakeChatStream(platform="")) == ""


def test_block_warns_against_inventing_relationship() -> None:
    """必须提醒不要编造与对方的关系。

    实测中它对陌生人说"你咋不知道我"，属于凭空捏造熟识关系。
    """

    block = build_scene_context_block(_FakeChatStream(user_nickname="某人"))

    assert "不要编造" in block


def test_account_profile_is_injected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """适配器写出的账号资料应出现在场景说明里。"""

    plugin_dir = tmp_path / "data" / "plugins" / "demo.adapter"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "account_profile.json").write_text(
        json.dumps(
            {
                "platform": "telegram",
                "user_id": "1000000001",
                "username": "testuser",
                "display_name": "Grayson",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    block = build_scene_context_block(_FakeChatStream(user_nickname="对方"))

    assert "Grayson" in block
    assert "@testuser" in block


def test_missing_profile_is_tolerated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """没有账号资料文件时应照常输出场景，只是少了账号信息。"""

    monkeypatch.chdir(tmp_path)
    block = build_scene_context_block(_FakeChatStream(user_nickname="对方"))

    assert "Telegram" in block
    assert "私聊" in block


def test_corrupted_profile_is_tolerated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """账号资料损坏时不应抛异常。"""

    plugin_dir = tmp_path / "data" / "plugins" / "demo.adapter"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "account_profile.json").write_text("{ 这不是合法 json", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    block = build_scene_context_block(_FakeChatStream(user_nickname="对方"))

    assert "私聊" in block


def test_personality_survives_missing_chat_stream() -> None:
    """场景说明失败不得让整个人设 prompt 降级。

    回归：早期实现直接访问 ``self.chat_stream``，在该属性尚未装配时
    抛 AttributeError，被上层 except 吞掉后人设静默退化成
    "你的名字是麦麦"，人格设定全部丢失。
    """

    from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator
    from src.config.config import global_config

    # 绕过 __init__，模拟 chat_stream 未装配的情形。
    generator = object.__new__(BaseMaisakaReplyGenerator)
    prompt = generator._build_personality_prompt()

    personality = global_config.personality.personality.strip()
    assert personality in prompt, "人设内容丢失，prompt 已降级"
