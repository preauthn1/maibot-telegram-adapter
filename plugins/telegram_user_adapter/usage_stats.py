"""用量统计与成本洞察。

为什么需要这个模块
------------------

借鉴 Hermes 的 token 用量追踪。Hermes 按模型、按会话记录消耗
并折算成本，让"这个月花了多少、花在哪"成为可查数据。

我们此前完全没有这一层。插件跑一整天发 533 条消息，背后消耗
多少 token、哪个群最烧钱、哪个模型占比最高——全靠猜。
这影响两件实际的事：

1. **成本控制**：DeepSeek 密钥池有 93 把 key，配额不是无限的。
   某个群在无意义地烧 token，需要数据才看得出来。
2. **异常发现**：某会话 token 突然暴涨，通常意味着上下文膨胀
   或陷入无意义长对话，两者都值得干预。

设计要点：
- 按 **模型** 与 **会话** 两个维度分别聚合
- prompt / completion 分开记账——单价通常不同
- 单价可配置，不硬编码某家价格（我们同时用 GLM、DeepSeek 等）
- 输出人可读洞察，而非一堆裸数字
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

_MILLION = 1_000_000.0


@dataclass(frozen=True)
class ModelPricing:
    """单个模型的计价（美元/百万 token）。

    Attributes:
        prompt_per_million: 输入 token 单价。
        completion_per_million: 输出 token 单价。
    """

    prompt_per_million: float
    completion_per_million: float

    def cost_for(self, prompt_tokens: int, completion_tokens: int) -> float:
        """按 token 数折算成本。

        Args:
            prompt_tokens: 输入 token 数。
            completion_tokens: 输出 token 数。

        Returns:
            float: 成本金额。
        """

        return (
            prompt_tokens / _MILLION * self.prompt_per_million
            + completion_tokens / _MILLION * self.completion_per_million
        )


@dataclass
class UsageBucket:
    """一个维度上的用量聚合。

    Attributes:
        prompt_tokens: 累计输入 token。
        completion_tokens: 累计输出 token。
        calls: 累计调用次数。
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        """输入与输出 token 之和。"""

        return self.prompt_tokens + self.completion_tokens

    def add(self, prompt: int, completion: int) -> None:
        """累加一次调用。

        Args:
            prompt: 本次输入 token。
            completion: 本次输出 token。
        """

        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.calls += 1


class UsageTracker:
    """记录 token 用量并给出成本洞察。"""

    def __init__(
        self, *, pricing: Optional[Mapping[str, ModelPricing]] = None
    ) -> None:
        """初始化追踪器。

        Args:
            pricing: 模型名到计价的映射；未配置的模型成本按 0 计。
        """

        self.pricing: Dict[str, ModelPricing] = dict(pricing or {})
        self._by_model: Dict[str, UsageBucket] = {}
        self._by_session: Dict[str, UsageBucket] = {}
        self._total = UsageBucket()

    def record(
        self, *, model: str, session: str, prompt: int, completion: int
    ) -> None:
        """记录一次模型调用的用量。

        Args:
            model: 模型名。
            session: 会话标识。
            prompt: 输入 token 数。
            completion: 输出 token 数。
        """

        if prompt < 0 or completion < 0:
            return

        self._total.add(prompt, completion)
        self._by_model.setdefault(model, UsageBucket()).add(prompt, completion)
        self._by_session.setdefault(session, UsageBucket()).add(prompt, completion)

    def totals(self) -> UsageBucket:
        """返回全局累计用量。"""

        return self._total

    def by_model(self) -> Dict[str, UsageBucket]:
        """返回按模型聚合的用量。"""

        return dict(self._by_model)

    def by_session(self) -> Dict[str, UsageBucket]:
        """返回按会话聚合的用量。"""

        return dict(self._by_session)

    def total_cost(self) -> float:
        """按各模型单价折算总成本。

        未配置单价的模型计 0——算不出钱不代表要崩，
        但报告里会显示 token 数，便于发现漏配。

        Returns:
            float: 总成本。
        """

        cost = 0.0
        for model, bucket in self._by_model.items():
            price = self.pricing.get(model)
            if price is None:
                continue
            cost += price.cost_for(bucket.prompt_tokens, bucket.completion_tokens)
        return cost

    def average_tokens_per_call(self) -> float:
        """返回平均单次调用消耗的 token。

        这是上下文膨胀的早期信号：同样的聊天场景，均值持续上升
        说明历史越带越长。

        Returns:
            float: 平均 token；无调用时返回 0。
        """

        if self._total.calls == 0:
            return 0.0
        return self._total.total_tokens / self._total.calls

    def top_sessions(self, limit: int = 5) -> List[Tuple[str, UsageBucket]]:
        """返回消耗最高的若干会话。

        Args:
            limit: 返回条数。

        Returns:
            List[Tuple[str, UsageBucket]]: 按 token 降序。
        """

        ranked = sorted(
            self._by_session.items(),
            key=lambda item: item[1].total_tokens,
            reverse=True,
        )
        return ranked[:limit]

    def build_report(self, *, top_limit: int = 5) -> str:
        """构造人可读的用量洞察摘要。

        Args:
            top_limit: 会话排行的条数。

        Returns:
            str: 报告文本。
        """

        if self._total.calls == 0:
            return "暂无用量数据"

        lines = [
            f"总调用 {self._total.calls} 次，"
            f"token {self._total.total_tokens}"
            f"（入 {self._total.prompt_tokens} / 出 {self._total.completion_tokens}）",
            f"平均单次 {self.average_tokens_per_call():.0f} token",
        ]

        cost = self.total_cost()
        unpriced = [m for m in self._by_model if m not in self.pricing]
        if cost > 0:
            lines.append(f"估算成本 ${cost:.4f}")
        if unpriced:
            lines.append(f"未配单价（成本未计入）: {', '.join(sorted(unpriced))}")

        lines.append("")
        lines.append("按模型:")
        for model, bucket in sorted(
            self._by_model.items(),
            key=lambda item: item[1].total_tokens,
            reverse=True,
        ):
            share = bucket.total_tokens / self._total.total_tokens * 100
            lines.append(
                f"  {model}: {bucket.total_tokens} token"
                f"（{share:.1f}%，{bucket.calls} 次）"
            )

        lines.append("")
        lines.append(f"消耗最高的 {top_limit} 个会话:")
        for session, bucket in self.top_sessions(limit=top_limit):
            avg = bucket.total_tokens / bucket.calls if bucket.calls else 0.0
            lines.append(
                f"  {session}: {bucket.total_tokens} token"
                f"（{bucket.calls} 次，均 {avg:.0f}）"
            )

        return "\n".join(lines)
