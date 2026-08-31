"""安全拦截不得依赖 humanize 开关。

回归审计发现 detect_pollution / review_draft / high_risk_should_block
三道核心拦截全部缩在 `if self._enable_humanize:` 块内。
`enable_humanize` 是**文本改写**开关（config.py 可配），
把它关掉本意是"不要改写我的话"，却顺带关掉了安全检查。

实测（enable_humanize=False）：
  '假false'              → 已发出
  'assistant: 好的'      → 已发出
  '{"role": "user"}'     → 已发出
  '作为一个AI我不能这么说' → 已发出（教训库拦截失效）
  高风险群 24 字长句      → 已发出（max_chars=20 失效）

「假false」正是导致账号被质疑的原始事故文本——中英混杂的布尔值，
9 秒前刚有人问过"ai？"。注释里写着"一次泄漏就足以暴露"，
却被一个改写开关关掉了。

NSFW 检测已正确放在开关外面，这三道照此办理。
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.output_sanity import detect_pollution  # noqa: E402


def _source() -> str:
    """读出站编解码器源码，用于结构断言。"""

    path = (
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "telegram_user_adapter"
        / "codecs"
        / "outbound.py"
    )
    return path.read_text(encoding="utf-8")


def _indent_of(source: str, needle: str) -> int:
    """返回某行的缩进空格数。"""

    for line in source.splitlines():
        if needle in line:
            return len(line) - len(line.lstrip())
    raise AssertionError(f"源码中找不到 {needle!r}")


def test_pollution_check_not_gated_by_humanize() -> None:
    """污染检测必须在 humanize 开关之外。

    「假false」是真实事故文本，一次泄漏就足以暴露身份。
    """

    source = _source()

    nsfw_indent = _indent_of(source, "is_nsfw, nsfw_hits = detect_nsfw(text)")
    pollution_indent = _indent_of(source, "polluted, reasons = detect_pollution(text)")

    assert pollution_indent <= nsfw_indent, (
        "detect_pollution 的缩进深于 NSFW 检测，说明它还在 "
        "if self._enable_humanize 块内——关掉改写开关就会失去这道防护"
    )


def test_lesson_review_not_gated_by_humanize() -> None:
    """发言前自检（教训库）必须在 humanize 开关之外。"""

    source = _source()

    nsfw_indent = _indent_of(source, "is_nsfw, nsfw_hits = detect_nsfw(text)")
    review_indent = _indent_of(source, "verdict = review_draft(text")

    assert review_indent <= nsfw_indent, (
        "review_draft 仍在 humanize 块内，关掉改写就不再检查已知失败模式"
    )


def test_high_risk_block_not_gated_by_humanize() -> None:
    """高风险群约束必须在 humanize 开关之外。"""

    source = _source()

    nsfw_indent = _indent_of(source, "is_nsfw, nsfw_hits = detect_nsfw(text)")
    risk_indent = _indent_of(source, "blocked, block_reason = high_risk_should_block(")

    assert risk_indent <= nsfw_indent, (
        "high_risk_should_block 仍在 humanize 块内，"
        "关掉改写后高风险群的长度与语气约束全部失效"
    )


def test_pollution_detector_catches_incident_text() -> None:
    """确认检测器本身能识别真实事故文本（防止拦截被移到外面但形同虚设）。"""

    polluted, reasons = detect_pollution("假false")

    assert polluted, f"未能识别真实事故文本「假false」，命中={reasons}"
