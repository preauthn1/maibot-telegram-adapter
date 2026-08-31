"""挑衅回应必须经过全部六道闸门。

被骂时恰恰是最需要克制的时刻——对方一直骂、我们就一直接话，
正中下怀。而这条路径曾经直接调 client.send_message，绕过一切。

上一轮把它改成走 send_queue，补上了全局串行、静默时段复检、
打字模拟三道。但回归审计实测发现**另外三道仍在绕过**：
连发上限（该群计数 99 > limit 3 仍照发）、发送预算、注意力焦点
——因为后两者实现在 codecs/outbound.py 的 send_outbound_message
里，而这条路径不走 codec。

本测试用源码结构断言锁定六道全覆盖，防止再退回去。
"""

from pathlib import Path


def _provocation_source() -> str:
    """截取 _send_provocation_reply 的函数体。"""

    path = (
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "telegram_user_adapter"
        / "plugin.py"
    )
    source = path.read_text(encoding="utf-8")

    start = source.index("async def _send_provocation_reply")
    # 到下一个同级方法定义为止
    end = source.index("\n    async def ", start + 10)
    return source[start:end]


def test_provocation_respects_consecutive_limit() -> None:
    """连发上限：对方连骂时不能无限接话。"""

    body = _provocation_source()

    assert "_is_consecutive_limited" in body, (
        "挑衅回应没有检查连发上限——被骂时是最需要克制的时刻，"
        "却成了唯一能突破上限的路径"
    )


def test_provocation_respects_send_budget() -> None:
    """发送预算：这条路径不走 codec，必须自己查。"""

    body = _provocation_source()

    assert "_send_budget.check()" in body, "挑衅回应绕过了发送预算"
    assert "_send_budget.record()" in body, (
        "挑衅回应发出后没记账，这条消息在预算统计里凭空消失"
    )


def test_provocation_respects_attention_focus() -> None:
    """注意力焦点：真人不会同一时段在十几个群里活跃。"""

    body = _provocation_source()

    assert "_attention.check(" in body, "挑衅回应绕过了注意力焦点"
    assert "_attention.record(" in body, "挑衅回应发出后没刷新焦点"


def test_provocation_goes_through_queue() -> None:
    """全局串行 + 静默时段复检 + 打字模拟：靠走队列获得。"""

    body = _provocation_source()

    assert "queue.submit(" in body, "挑衅回应没走发送队列"
    assert "QuietHoursError" in body, "没有处理静默时段"
    assert "asyncio.sleep(" in body, "没有打字停顿——秒回固定话术是最扎眼的脚本特征"


def test_provocation_rolls_back_on_failure() -> None:
    """任何失败路径都要归还预占的连发名额。

    不还的话，几次失败后该群就再也不会回应挑衅了。
    """

    body = _provocation_source()

    release_count = body.count("_release_consecutive(")

    # 预算拦截、焦点拦截、静默时段、发送异常，共 4 条失败路径
    assert release_count >= 4, (
        f"只有 {release_count} 处回滚，少于失败路径数量——"
        "有路径漏了归还名额"
    )
