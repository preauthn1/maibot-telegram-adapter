"""广告识别测试。

硬性要求：看到广告不理。跟广告搭话既烧 token 又暴露身份
（真人划过去，只有机器人逐条认真回）。

误伤正常聊天比漏掉广告更严重——被误伤意味着该回的话没回，
所以正常样本必须全部放行。
"""

from __future__ import annotations

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.spam_filter import detect_spam  # noqa: E402


def test_real_spam_sample_from_production() -> None:
    """线上真实广告：用零宽字符切断关键词绕过检测。"""

    text = "零风险小\u200c额洗米日入\u200d8K\u200b"
    is_spam, signals = detect_spam(text)
    assert is_spam
    # 零宽字符必须被识别出来
    assert any("invisible" in s for s in signals)


def test_zero_width_obfuscation_alone_is_enough() -> None:
    """仅凭零宽字符混淆即可判定——正常人不会这么打字。"""

    is_spam, _ = detect_spam("正\u200b常\u200c文\u200d字")
    assert is_spam


def test_single_zero_width_not_enough() -> None:
    """单个零宽字符可能来自复制粘贴，不足以判定。"""

    is_spam, _ = detect_spam("你好\u200b")
    assert not is_spam


def test_gambling_and_laundering_keywords() -> None:
    """灰产词是强信号，单独命中即判定。"""

    for text in [
        "承兑跑分资金盘招代理",
        "四方支付接口料出黑",
        "菠菜网投返水高",
    ]:
        is_spam, _ = detect_spam(text)
        assert is_spam, f"{text!r} 未被识别"


def test_profit_lure_with_contact() -> None:
    """收益诱导 + 引流方式的组合。"""

    is_spam, _ = detect_spam("日入8000+ 加V详聊")
    assert is_spam


def test_invite_link_with_contact() -> None:
    """邀请链接 + 引流。"""

    is_spam, _ = detect_spam("t.me/+abc123 加微信详聊")
    assert is_spam


def test_normal_chat_never_flagged() -> None:
    """正常聊天必须全部放行 —— 误伤比漏检更糟。"""

    normal = [
        "早啊",
        "肝到天亮吗这是",
        "这个电子产品不错",
        "搬瓦工cn2 gia那个还行",
        "我加你微信吧",
        "咨询一下这个怎么用",
        "点位在哪看",
        "日子过得真快",
        "这游戏收益率挺高的",
        "冒菜就是不用自己煮的麻辣烫吧",
        "25发了啊 出金没",
        "",
    ]
    for text in normal:
        is_spam, signals = detect_spam(text)
        assert not is_spam, f"{text!r} 被误判为广告，信号={signals}"


def test_ambiguous_words_need_more_signals() -> None:
    """\"电子\"\"点位\"这类词单独出现不能判定为广告。"""

    for text in ["电子发票怎么开", "点位设置在哪", "代发快递吗"]:
        is_spam, _ = detect_spam(text)
        assert not is_spam, f"{text!r} 被误判"
