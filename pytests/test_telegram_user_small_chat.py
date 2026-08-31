"""小群参与率与接话节奏测试。

真实事故（某休闲小群 -1009000000002，8-30 21:09）：

    21:09:06 【我们】  ⚡4秒接话
    21:09:16 【我们】  ⚡4秒接话
    21:09:33 【我们】  ⚡1秒接话
    21:09:47 【我们】  ⚡2秒接话
    21:09:56 对方: "ai？"

50 秒内秒回 4 次直接触发怀疑。人在手机上光是读完一句话就不止
1 秒，更别说还要打字。这是被识破的直接原因——不是内容问题。

该群参与率实测 63.6%（入站 55、出站 35），而技术群只有 12-13%。
"""

from __future__ import annotations

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.small_chat import (  # noqa: E402
    READ_DELAY_MIN_SECONDS,
    SMALL_CHAT_REPLY_RATIO,
    SmallChatModerator,
    estimate_read_delay,
    is_farewell,
)

GENSHIN = "-1009000000002"


def test_read_delay_never_allows_instant_reply() -> None:
    """⚠️ 核心：绝不能出现 1 秒接话——这正是被识破的原因。"""

    for text in ["嗯", "加油", "这时间安排得明明白白", "x" * 200]:
        for _ in range(50):
            assert estimate_read_delay(text) >= READ_DELAY_MIN_SECONDS


def test_read_delay_scales_with_length() -> None:
    """长消息要读更久。"""

    short = [estimate_read_delay("嗯") for _ in range(60)]
    long_text = [estimate_read_delay("x" * 300) for _ in range(60)]
    assert sum(long_text) / len(long_text) > sum(short) / len(short)


def test_read_delay_is_randomized() -> None:
    """延迟必须随机——固定延迟同样是可识别的规律。"""

    values = {round(estimate_read_delay("测试消息"), 3) for _ in range(50)}
    assert len(values) > 20


def test_rapid_consecutive_replies_suppressed() -> None:
    """复现事故节奏：连续快速接话必须被拦下。"""

    mod = SmallChatModerator()
    mod.record_outbound(GENSHIN, "这时间安排得明明白白", now=1000.0)

    # 事故中 1 秒后又发了一条
    suppressed, reason = mod.should_suppress(
        GENSHIN, member_count=4, now=1001.0
    )
    assert suppressed, f"1 秒接话未被拦截: {reason}"


def test_small_chat_ratio_capped() -> None:
    """小群参与率超限后应当忍住。"""

    mod = SmallChatModerator()
    for i in range(10):
        mod.record_inbound(GENSHIN, now=1000.0 + i)
    # 已经回了 6 条 = 60%，远超上限
    for i in range(6):
        mod.record_outbound(GENSHIN, "话", now=1000.0 + i)

    suppressed, reason = mod.should_suppress(
        GENSHIN, member_count=4, now=1100.0
    )
    assert suppressed
    assert "参与率" in reason


def test_large_chat_not_ratio_capped() -> None:
    """大群不压参与率——同样的发言量会被人数稀释掉。"""

    mod = SmallChatModerator()
    for i in range(10):
        mod.record_inbound("-100BIG", now=1000.0 + i)
    for i in range(6):
        mod.record_outbound("-100BIG", "话", now=1000.0 + i)

    suppressed, _ = mod.should_suppress("-100BIG", member_count=50, now=1100.0)
    assert not suppressed


def test_directed_message_still_answered() -> None:
    """被 @ 时要正常回应——装死同样不像真人。"""

    mod = SmallChatModerator()
    for i in range(10):
        mod.record_inbound(GENSHIN, now=1000.0 + i)
    for i in range(6):
        mod.record_outbound(GENSHIN, "话", now=1000.0 + i)

    suppressed, _ = mod.should_suppress(
        GENSHIN, member_count=4, is_directed=True, now=1100.0
    )
    assert not suppressed


def test_farewell_detection() -> None:
    """道别语识别。"""

    for text in ["我先躺了", "我睡了", "睡觉去了", "不聊了", "晚安", "我先撤"]:
        assert is_farewell(text), f"{text!r} 未被识别为道别"

    for text in ["这图真阴间", "37发没出", "睡不着"]:
        assert not is_farewell(text), f"{text!r} 被误判为道别"


def test_farewell_triggers_real_silence() -> None:
    """⚠️ 说了"我睡了"就要真的消失。

    事故中 09:07 说"我先躺了"，51 分钟后又出现；
    10:00 说"别闹 我睡了"，27 分钟后又跳出来接话。
    """

    mod = SmallChatModerator()
    mod.record_outbound(GENSHIN, "别闹 我睡了", now=1000.0)

    # 27 分钟后（事故中的实际情况）仍应保持沉默
    suppressed, reason = mod.should_suppress(
        GENSHIN, member_count=4, now=1000.0 + 27 * 60
    )
    assert suppressed, "道别后 27 分钟就重新说话，正是事故中的表现"
    assert "静默" in reason


def test_farewell_silence_ignores_mention() -> None:
    """道别静默期内即使被 @ 也保持沉默，否则"我睡了"就成了谎话。"""

    mod = SmallChatModerator()
    mod.record_outbound(GENSHIN, "我先躺了", now=1000.0)

    suppressed, _ = mod.should_suppress(
        GENSHIN, member_count=4, is_directed=True, now=1000.0 + 600
    )
    assert suppressed


def test_ratio_limit_matches_tech_groups() -> None:
    """上限需高于线上实测参与率，同时远低于某休闲小群的 63%。

    2026-08-31 实测九个白名单群整体参与率仅 6.9%（最低群 1.7%），
    说明 0.30 的旧上限从未成为瓶颈——真正的压制来自发言间隔。
    上限放宽到 0.45 以留出活跃空间，上界仍卡在 0.50 以下，
    避免退回"别人说 3 句我们接 2 句"的刷屏状态。
    """

    assert 0.15 <= SMALL_CHAT_REPLY_RATIO <= 0.50


def test_window_prunes_old_records() -> None:
    """窗口外的记录要丢弃，避免长期运行内存膨胀。"""

    mod = SmallChatModerator(window=100.0)
    for i in range(50):
        mod.record_inbound(GENSHIN, now=1000.0 + i)

    mod.record_inbound(GENSHIN, now=5000.0)
    stats = mod.stats(GENSHIN)
    assert stats["inbound"] < 5


def test_farewell_not_triggered_by_technical_talk() -> None:
    """技术讨论里的常用词不该被当成道别。

    审计发现的 P0：道别正则全是无锚定子串匹配，技术群里说
    「镜像下了」「他睡了没」都会命中，导致账号立刻进入
    40-120 分钟静默。更糟的是静默检查在 is_directed 之前，
    静默期内被 @ 也不回——正是"被点名还在潜水"的行为异常。
    """

    false_positives = [
        "我下了个 app",
        "把镜像下了",
        "下了单等发货",
        "娃睡了终于清静",
        "他睡了没",
        "猫睡了",
        "他明天见客户",
        "说好明天见面的",
        "昨晚晚安都没说",
        "不说了这个话题太敏感",
        "我先撤回一下",
        "我先走一步这个方案",
    ]

    wrongly_matched = [text for text in false_positives if is_farewell(text)]

    assert not wrongly_matched, f"这些不是道别却被误判：{wrongly_matched}"


def test_real_farewell_still_detected() -> None:
    """真正的道别仍要能识别——修窄不能修死。"""

    real_farewells = [
        "我先睡了",
        "睡了",
        "晚安",
        "不聊了",
        "下线了",
        "明天见",
        "我先撤了",
        "睡觉去了",
    ]

    missed = [text for text in real_farewells if not is_farewell(text)]

    assert not missed, f"这些是道别却没识别出来：{missed}"
