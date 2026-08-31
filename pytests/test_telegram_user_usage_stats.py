"""用量统计与成本洞察测试（借鉴 Hermes 的 token 用量追踪）。

Hermes 会按模型、按会话记录 token 消耗并折算成本，让"这个月
花了多少、花在哪"变成可查的数据而不是猜测。

我们此前完全没有这一层：插件跑了一整天，发了 533 条消息，
背后消耗多少 token、哪个群最烧钱、哪个模型占比最高，全都不知道。
这直接影响两件事：

1. **成本控制**：DeepSeek 密钥池有 93 把 key，但配额不是无限的。
   哪个群在无意义地烧 token，需要数据才能看出来。
2. **异常发现**：某个群突然 token 暴涨，往往意味着上下文膨胀
   或陷入了无意义的长对话——这两种都值得干预。

设计要点（沿用 Hermes 的做法）：
- 按 **模型** 和 **会话** 两个维度分别聚合
- 记录 prompt/completion 分开——两者单价通常不同
- 成本按可配置单价折算，不硬编码某家的价格
- 提供人可读的洞察摘要，而不只是一堆数字
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.usage_stats import (  # noqa: E402
    ModelPricing,
    UsageTracker,
)


def test_record_accumulates_tokens() -> None:
    """基本累加。"""

    tracker = UsageTracker()
    tracker.record(model="glm-5.3-flash", session="chat-a", prompt=100, completion=50)
    tracker.record(model="glm-5.3-flash", session="chat-a", prompt=200, completion=80)

    total = tracker.totals()

    assert total.prompt_tokens == 300
    assert total.completion_tokens == 130
    assert total.calls == 2


def test_per_model_breakdown() -> None:
    """按模型拆分——要能看出哪个模型占比最高。"""

    tracker = UsageTracker()
    tracker.record(model="glm-5.3-flash", session="chat-a", prompt=100, completion=50)
    tracker.record(model="deepseek-chat", session="chat-a", prompt=400, completion=200)

    by_model = tracker.by_model()

    assert by_model["glm-5.3-flash"].total_tokens == 150
    assert by_model["deepseek-chat"].total_tokens == 600


def test_per_session_breakdown() -> None:
    """按会话拆分——要能看出哪个群最烧 token。"""

    tracker = UsageTracker()
    tracker.record(model="m1", session="chat-a", prompt=100, completion=50)
    tracker.record(model="m1", session="chat-b", prompt=900, completion=100)

    by_session = tracker.by_session()

    assert by_session["chat-a"].total_tokens == 150
    assert by_session["chat-b"].total_tokens == 1000


def test_cost_uses_separate_prices() -> None:
    """prompt 与 completion 单价不同，必须分开计价。"""

    pricing = {
        "m1": ModelPricing(prompt_per_million=1.0, completion_per_million=2.0),
    }
    tracker = UsageTracker(pricing=pricing)
    tracker.record(model="m1", session="chat-a", prompt=1_000_000, completion=1_000_000)

    # 1.0 + 2.0 = 3.0
    assert abs(tracker.total_cost() - 3.0) < 1e-9


def test_unknown_model_costs_zero_not_crash() -> None:
    """没配单价的模型不应崩，只是算不出钱。"""

    tracker = UsageTracker(pricing={})
    tracker.record(model="mystery", session="chat-a", prompt=1000, completion=500)

    assert tracker.total_cost() == 0.0
    assert tracker.totals().total_tokens == 1500


def test_top_sessions_sorted_by_tokens() -> None:
    """洞察的核心：按消耗排序找出大头。"""

    tracker = UsageTracker()
    tracker.record(model="m1", session="small", prompt=10, completion=10)
    tracker.record(model="m1", session="huge", prompt=5000, completion=1000)
    tracker.record(model="m1", session="mid", prompt=500, completion=100)

    top = tracker.top_sessions(limit=2)

    assert [name for name, _ in top] == ["huge", "mid"]


def test_insight_report_is_human_readable() -> None:
    """要给人看的摘要，不是裸数据。"""

    pricing = {"m1": ModelPricing(prompt_per_million=0.5, completion_per_million=1.5)}
    tracker = UsageTracker(pricing=pricing)
    tracker.record(model="m1", session="chat-a", prompt=100_000, completion=20_000)

    report = tracker.build_report()

    assert "总调用" in report
    assert "m1" in report
    assert "chat-a" in report


def test_empty_tracker_report_says_so() -> None:
    """没数据时明确说没数据，不要输出一堆 0 让人误以为是真实值。"""

    report = UsageTracker().build_report()

    assert "暂无" in report


def test_average_tokens_per_call() -> None:
    """平均单次消耗——上下文膨胀的早期信号。"""

    tracker = UsageTracker()
    tracker.record(model="m1", session="chat-a", prompt=100, completion=100)
    tracker.record(model="m1", session="chat-a", prompt=300, completion=100)

    assert tracker.average_tokens_per_call() == 300.0
