"""高风险群约束测试。

模拟一个熟人小圈子的画像：人少、安静、句子极短、话题专业。
实测中这类群里只发一条就会被当面质问是不是 AI。

画像本身来自 data/plugins/<id>/chats/<chat_id>/SKILL.md，
测试里用 tmp 目录构造，不依赖真实群数据。
"""

from __future__ import annotations

from pathlib import Path

import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter import high_risk_chats as hr  # noqa: E402
from telegram_user_adapter.high_risk_chats import (  # noqa: E402
    blocks_tech,
    get_max_chars,
    get_min_gap,
    get_reply_ratio,
    is_high_risk,
    is_tech_topic,
    should_block,
    sounds_like_explainer,
)
from telegram_user_adapter.small_chat import SmallChatModerator  # noqa: E402

PROXY_CHAT = "-1009000000001"
NORMAL_CHAT = "-1009000000003"

# 高风险群画像：对应"14 人、3.2 条/小时、中位 13 字"这类圈子
_HIGH_RISK_CARD = """---
title: "高风险小群"
max_chars: 23
reply_ratio: 0.08
min_gap_seconds: 900
block_tech: true
---

# 高风险小群

人少、安静、话题专业，新面孔话多会被迅速聚焦。
"""

# 低风险群画像：人多话杂，不设约束
_NORMAL_CARD = """---
title: "普通群"
---

# 普通群

人多话杂，发言会被稀释。
"""


@pytest.fixture(autouse=True)
def _bind_profiles(tmp_path: Path):
    """为每个用例准备画像卡目录并绑定。

    高风险画像不再硬编码在代码里，测试也就必须自带画像卡——
    这样测的才是真实的加载链路。
    """

    for chat_id, card in ((PROXY_CHAT, _HIGH_RISK_CARD), (NORMAL_CHAT, _NORMAL_CARD)):
        chat_dir = tmp_path / chat_id
        chat_dir.mkdir(parents=True, exist_ok=True)
        (chat_dir / "SKILL.md").write_text(card, encoding="utf-8")

    hr.bind_store(tmp_path)
    yield
    hr._STORE = None


def test_proxy_chat_marked_high_risk() -> None:
    """高风险小群必须在高风险名单内。"""

    assert is_high_risk(PROXY_CHAT)
    assert not is_high_risk(NORMAL_CHAT)


def test_long_message_blocked() -> None:
    """⚠️ 该群中位仅 13 字，长句子一眼就不是圈内人。"""

    long_text = "这个协议的实现方式其实挺有意思的，它通过伪装握手来绕过检测机制"
    blocked, reason = should_block(PROXY_CHAT, long_text)
    assert blocked
    assert "长度" in reason


def test_short_message_allowed() -> None:
    """短句符合群内语感，应当放行。"""

    for text in ["太对了", "发过n次了", "这什么鬼", "JLS 是什么"]:
        blocked, reason = should_block(PROXY_CHAT, text)
        assert not blocked, f"{text!r} 被误拦: {reason}"


def test_explainer_tone_blocked() -> None:
    """讲解腔是最明显的破绽——圈内人不会这么起头。"""

    for text in ["简单来说就这样", "也就是说会崩", "换句话说不行"]:
        blocked, reason = should_block(PROXY_CHAT, text)
        assert blocked, f"{text!r} 未被拦截"
        assert "讲解腔" in reason or "长度" in reason


def test_explainer_detection() -> None:
    """讲解腔识别本身。"""

    assert sounds_like_explainer("简单来说，这个协议很快")
    assert sounds_like_explainer("也就是说它会崩")
    assert not sounds_like_explainer("这玩意儿会崩")
    assert not sounds_like_explainer("太对了")


def test_normal_chat_unaffected() -> None:
    """非高风险群不受长度约束——别误伤正常聊天。"""

    long_text = "这个协议的实现方式其实挺有意思的，通过伪装握手绕过检测"
    blocked, _ = should_block(NORMAL_CHAT, long_text)
    assert not blocked


def test_profile_values_match_observed_data() -> None:
    """画像参数要贴合实测数据。"""

    # 中位 13 字，上限给到 24 字留出余量但不放任
    assert 15 <= get_max_chars(PROXY_CHAT) <= 30
    # 2.4 条/小时的群，参与率必须极低
    assert get_reply_ratio(PROXY_CHAT) <= 0.10
    # 间隔至少十几分钟
    assert get_min_gap(PROXY_CHAT) >= 600


def test_ratio_override_applies_regardless_of_member_count() -> None:
    """⚠️ 高风险群有 13 人，超过小群阈值，
    但仍必须压制——熟人技术圈里新面孔话多最扎眼。"""

    mod = SmallChatModerator()
    for i in range(10):
        mod.record_inbound(PROXY_CHAT, now=1000.0 + i)
    for i in range(2):
        mod.record_outbound(PROXY_CHAT, "嗯", now=1000.0 + i)

    # member_count=13 远超 SMALL_CHAT_MEMBER_LIMIT
    suppressed, reason = mod.should_suppress(
        PROXY_CHAT,
        member_count=13,
        now=2000.0,
        ratio_override=get_reply_ratio(PROXY_CHAT),
        min_gap_override=get_min_gap(PROXY_CHAT),
    )
    assert suppressed, f"高风险群未被压制: {reason}"


def test_normal_chat_large_group_not_suppressed() -> None:
    """普通大群仍不压参与率——发言量会被人数稀释。"""

    mod = SmallChatModerator()
    for i in range(10):
        mod.record_inbound(NORMAL_CHAT, now=1000.0 + i)
    for i in range(6):
        mod.record_outbound(NORMAL_CHAT, "话", now=1000.0 + i)

    suppressed, _ = mod.should_suppress(NORMAL_CHAT, member_count=50, now=2000.0)
    assert not suppressed


def test_directed_still_answered_in_high_risk() -> None:
    """被当面 @ 时仍要回应——那条 "你是大语言模型吗？" 至今没回，
    长期沉默本身也是一种回答。"""

    mod = SmallChatModerator()
    for i in range(10):
        mod.record_inbound(PROXY_CHAT, now=1000.0 + i)
    for i in range(5):
        mod.record_outbound(PROXY_CHAT, "嗯", now=1000.0 + i)

    suppressed, _ = mod.should_suppress(
        PROXY_CHAT,
        member_count=13,
        is_directed=True,
        now=2000.0,
        ratio_override=get_reply_ratio(PROXY_CHAT),
    )
    assert not suppressed


def test_tech_topics_blocked_in_proxy_chat() -> None:
    """⚠️ 该群全是资深从业者，技术话题说浅了露怯、说深了更可疑。"""

    assert blocks_tech(PROXY_CHAT)
    assert not blocks_tech(NORMAL_CHAT)

    # 均为该群真实出现过的消息
    for text in [
        "今日份🇺🇸节点乱炖之：\n\nVLESS+JLS+TCP Brutal",
        "JLS 是什么",
        "我们 VPN 娱乐圈的协议到现在也就 WireGuard 算新的",
        "Pixel 11 疑似为了减轻内存压力删除了内存标记扩展（MTE）功能",
        "凡是根据 GPL、MIT、BSD 和 Apache 许可证分发的软件均符合豁免条件",
        "opwrt想发挥出来性能只有mihomo内核",
        "上海电信部分地区断网",
        "https://github.com/JimmyHuang454/JLS",
    ]:
        assert is_tech_topic(text), f"技术话题漏判: {text[:40]!r}"


def test_casual_chat_not_blocked() -> None:
    """闲聊要放行——全都不说话同样不像真人。"""

    for text in [
        "世界好凶",
        "中国人自古吃苦耐劳",
        "中国人会飞😭",
        "本来以为是最强反派, 没想到出场即巅峰",
        "太对了",
        "默哀一秒钟",
        "飞到一半发现鞘翅是假的",
    ]:
        assert not is_tech_topic(text), f"闲聊被误判为技术: {text!r}"
