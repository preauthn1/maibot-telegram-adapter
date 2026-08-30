"""Telegram 真人账号适配器拟人化组件测试。

覆盖：
- humanize：中文群聊改写（书面语、助手腔、markdown、emoji、标点）
- send_queue：静默时段判定、优先级排序、全局串行
- presence：按需上线 / 延迟下线
- self_improvement：怀疑检测、经验累积、SOUL/SKILL 文件生成
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncio
import sys

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins"
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from telegram_user_adapter.humanize import (  # noqa: E402
    humanize_chat_text,
    is_emoji_only,
    jitter,
    should_reply_briefly,
)
from telegram_user_adapter.config import TelegramUserChatConfig  # noqa: E402
from telegram_user_adapter.filters import TelegramUserChatFilter  # noqa: E402
from telegram_user_adapter.presence import PresenceManager  # noqa: E402
from telegram_user_adapter.self_improvement import (  # noqa: E402
    ChatOutcome,
    SelfImprovementStore,
    detect_suspicion,
)
from telegram_user_adapter.send_queue import (  # noqa: E402
    PRIORITY_MENTION,
    PRIORITY_NORMAL,
    QuietHoursError,
    SendQueue,
    is_quiet_hours,
    seconds_until_quiet_end,
)

_CN_TZ = timezone(timedelta(hours=8))


class _StubLogger:
    """测试用的静默日志器。"""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def _record(self, msg: object) -> None:
        self.messages.append(str(msg))

    debug = _record
    info = _record
    warning = _record
    error = _record


# ---------------------------------------------------------------------------
# humanize
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, must_not_contain",
    [
        ("此外，我觉得这个挺好的", "此外"),
        ("总的来说这事儿没啥问题", "总的来说"),
        ("希望这些对你有帮助", "希望"),
        ("好的，我这就去看看", "好的，"),
        ("有什么可以帮你的吗？", "可以帮"),
        ("**重点**是这个", "**"),
        ("# 标题\n内容", "#"),
        ("他说——其实没那么难", "——"),
        ("我看了《三体》", "《"),
        ("值得一提的是，这个功能很好用", "值得一提"),
    ],
)
def test_humanize_removes_ai_markers(text: str, must_not_contain: str) -> None:
    """书面语、助手腔、markdown、书面标点必须被清除。"""

    result = humanize_chat_text(text)

    assert must_not_contain not in result.text, f"{text!r} -> {result.text!r}"
    assert result.changed


def test_humanize_drops_trailing_period() -> None:
    """句尾句号应被去掉，问号感叹号保留。"""

    assert not humanize_chat_text("今天天气不错。").text.endswith("。")
    assert humanize_chat_text("你去吗？").text.endswith("？")
    assert humanize_chat_text("太强了！").text.endswith("！")


def test_humanize_limits_emoji() -> None:
    """emoji 数量应被限制，行首装饰 emoji 应删除。"""

    result = humanize_chat_text("🚀 今天 😀 很好 🎉 真的 ✨", max_emoji=1)

    assert not result.text.startswith("🚀")
    emoji_count = sum(1 for ch in result.text if ord(ch) > 0x1F000)
    assert emoji_count <= 1, result.text


def test_humanize_pure_assistant_tone_is_dropped() -> None:
    """整条都是助手腔时应标记为空，由调用方跳过发送。

    退回原文是错误的：那等于把最糟糕的 AI 味原样发出去。
    """

    for text in ["好的。", "有什么可以帮你的吗？", "希望这些对你有帮助", "很高兴为您服务。"]:
        result = humanize_chat_text(text)
        assert result.became_empty, f"未标记为空: {text!r} -> {result.text!r}"
        assert result.text == ""


def test_humanize_keeps_content_alongside_assistant_tone() -> None:
    """助手腔与真实内容混排时，应保留真实内容。"""

    result = humanize_chat_text("好的，那个文件我放桌面上了")

    assert not result.became_empty
    assert "文件" in result.text
    assert "桌面" in result.text
    assert not result.text.startswith("好的")


def test_humanize_preserves_normal_chat() -> None:
    """正常口语内容不应被大幅改动。"""

    text = "哈哈哈哈那你也太惨了吧"
    result = humanize_chat_text(text)

    assert result.text == text
    assert not result.changed


@pytest.mark.parametrize(
    "text",
    [
        "有什么好吃的推荐吗",
        "你有什么想法",
        "这有什么难的",
        "有啥事儿吗",
        "帮我看看这个",
        "谁能帮我一下",
        "我帮你问问",
        "有什么区别",
        "有什么好玩的",
        "今天有什么安排",
    ],
)
def test_humanize_does_not_break_normal_questions(text: str) -> None:
    """含"有什么/帮"的正常问句绝不能被误删。

    助手腔规则必须精确锚定完整客服套话，泛匹配会把
    "你有什么想法" 毁成 "你想法"。
    """

    result = humanize_chat_text(text)

    assert not result.became_empty, f"正常问句被判空: {text!r}"
    assert result.text == text, f"正常问句被改动: {text!r} -> {result.text!r}"


def test_humanize_does_not_invent_content() -> None:
    """拟人化只删不增，长度不应变长。"""

    for text in ["此外，这个方案我觉得可行", "**注意**：明天开会", "希望对你有帮助"]:
        result = humanize_chat_text(text)
        assert len(result.text) <= len(text), f"{text!r} -> {result.text!r}"


def test_should_reply_briefly() -> None:
    """短消息应建议短回复。"""

    assert should_reply_briefly("在吗")
    assert not should_reply_briefly("我今天遇到一个特别复杂的问题想请教一下大家的看法")


def test_jitter_stays_in_range() -> None:
    """抖动结果应落在预期区间内且非负。"""

    for _ in range(200):
        value = jitter(10.0, ratio=0.25)
        assert 7.5 <= value <= 12.5
    assert jitter(0.0) == 0.0


# ---------------------------------------------------------------------------
# emoji 单独回复
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["😂", "😂😂😂", "👍", "🤣🤣", "  😅  ", "...", "？？", "。", "😂!!!", "🙏🙏🙏🙏"],
)
def test_emoji_only_replies_are_detected(text: str) -> None:
    """纯 emoji / 纯标点回复必须被识别。

    只回一个 emoji 是最省事的敷衍回复，而且往往出现在没听懂的时候，
    正是最容易露馅的场合。
    """

    assert is_emoji_only(text), f"未识别为纯 emoji 回复: {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "哈哈哈😂",
        "😂 那你也太惨了",
        "行吧👍我知道了",
        "今天好累啊",
        "哈哈哈哈哈",
        "6",
        "在",
        "草",
    ],
)
def test_sentences_with_emoji_are_allowed(text: str) -> None:
    """emoji 作为句子辅助时必须放行，只有纯 emoji 才拦。"""

    assert not is_emoji_only(text), f"误判为纯 emoji 回复: {text!r}"


def test_empty_text_is_not_emoji_only() -> None:
    """空文本走既有的空值分支，不归类为纯 emoji。"""

    assert not is_emoji_only("")
    assert not is_emoji_only("   ")


def test_quiet_hours_across_midnight() -> None:
    """跨零点的静默区间（如 23:00-07:00）应正确判定。

    实测事故：静默检查原本只在出站，消息照常触发完整 LLM 推理，
    生成完回复才被丢弃（SendService error=quiet_hours），
    白烧推理且污染上下文。现已在入站侧提前拦截，
    该判定被更早、更频繁地调用，跨零点分支必须可靠。
    """

    from datetime import datetime, timedelta, timezone

    tz = timezone(timedelta(hours=8))

    def at(hour: int) -> datetime:
        return datetime(2026, 8, 31, hour, tzinfo=tz)

    assert is_quiet_hours(at(23), start_hour=23, end_hour=7)
    assert is_quiet_hours(at(2), start_hour=23, end_hour=7)
    assert not is_quiet_hours(at(8), start_hour=23, end_hour=7)


# ---------------------------------------------------------------------------
# 静默时段
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hour, expected", [(2, False), (3, True), (5, True), (6, True), (7, False), (12, False), (23, False)])
def test_quiet_hours_boundaries(hour: int, expected: bool) -> None:
    """UTC+8 03:00-07:00 为静默时段，边界须精确。"""

    now = datetime(2026, 8, 30, hour, 30, tzinfo=_CN_TZ)

    assert is_quiet_hours(now) is expected


def test_quiet_hours_uses_utc8_not_local() -> None:
    """必须按 UTC+8 判定，而不是服务器本地时区。"""

    # UTC 20:00 == UTC+8 次日 04:00，属于静默时段。
    utc_now = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)

    assert is_quiet_hours(utc_now) is True

    # UTC 02:00 == UTC+8 10:00，不静默。
    utc_now = datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)

    assert is_quiet_hours(utc_now) is False


def test_seconds_until_quiet_end() -> None:
    """剩余秒数计算应正确。"""

    now = datetime(2026, 8, 30, 5, 0, tzinfo=_CN_TZ)

    assert seconds_until_quiet_end(now, end_hour=7) == pytest.approx(2 * 3600)


# ---------------------------------------------------------------------------
# 发送队列
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_queue_serializes_globally() -> None:
    """所有群共用一条通道，任何时刻只能有一条消息在发送。"""

    queue = SendQueue(_StubLogger(), enable_quiet_hours=False, min_gap_seconds=0, max_gap_seconds=0)
    queue.start()

    concurrent = 0
    max_concurrent = 0

    async def _send(tag: str) -> str:
        nonlocal concurrent, max_concurrent
        concurrent += 1
        max_concurrent = max(max_concurrent, concurrent)
        await asyncio.sleep(0.02)
        concurrent -= 1
        return tag

    try:
        results = await asyncio.gather(
            *(queue.submit(lambda t=f"g{i}": _send(t), label=f"g{i}") for i in range(6))
        )
    finally:
        await queue.stop()

    assert len(results) == 6
    assert max_concurrent == 1, f"检测到并发发送: {max_concurrent}"


@pytest.mark.asyncio
async def test_send_queue_prioritizes_mentions() -> None:
    """被 @ 的群应优先于普通群出队。"""

    queue = SendQueue(_StubLogger(), enable_quiet_hours=False, min_gap_seconds=0, max_gap_seconds=0)
    order: list[str] = []
    blocker = asyncio.Event()

    async def _record(tag: str) -> None:
        order.append(tag)

    async def _block() -> None:
        await blocker.wait()

    queue.start()
    try:
        # 先占住 worker，确保后续任务都堆在队列里再释放。
        blocked = asyncio.create_task(queue.submit(_block, label="blocker"))
        await asyncio.sleep(0.05)

        normal_tasks = [
            asyncio.create_task(
                queue.submit(lambda t=f"normal{i}": _record(t), priority=PRIORITY_NORMAL, label=t)
            )
            for i, t in enumerate(["normal0", "normal1"])
        ]
        await asyncio.sleep(0.05)
        mention = asyncio.create_task(
            queue.submit(lambda: _record("mention"), priority=PRIORITY_MENTION, label="mention")
        )
        await asyncio.sleep(0.05)

        blocker.set()
        await asyncio.gather(blocked, mention, *normal_tasks)
    finally:
        await queue.stop()

    assert order[0] == "mention", f"提及未获得优先: {order}"


@pytest.mark.asyncio
async def test_send_queue_rejects_during_quiet_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    """静默时段内提交必须被拒绝，且不执行发送。"""

    queue = SendQueue(_StubLogger(), enable_quiet_hours=True)
    queue.start()
    monkeypatch.setattr(queue, "in_quiet_hours", lambda now=None: True)

    called = False

    async def _send() -> None:
        nonlocal called
        called = True

    try:
        with pytest.raises(QuietHoursError):
            await queue.submit(_send, label="g1")
    finally:
        await queue.stop()

    assert not called, "静默时段内不应执行发送"


@pytest.mark.asyncio
async def test_send_queue_propagates_errors() -> None:
    """发送异常必须回传给调用方，由其决定静默处理。"""

    queue = SendQueue(_StubLogger(), enable_quiet_hours=False, min_gap_seconds=0, max_gap_seconds=0)
    queue.start()

    async def _boom() -> None:
        raise RuntimeError("API 挂了")

    try:
        with pytest.raises(RuntimeError, match="API 挂了"):
            await queue.submit(_boom, label="g1")
    finally:
        await queue.stop()


# ---------------------------------------------------------------------------
# 自我改进
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "你是不是机器人",
        "你是AI吧",
        "这是个bot吧",
        "你说话好像机器人",
        "是不是人机",
        "复读机",
    ],
)
def test_detect_suspicion_positive(text: str) -> None:
    """怀疑话术必须被识别。"""

    assert detect_suspicion(text), text


@pytest.mark.parametrize(
    "text",
    ["今天天气不错", "你是南方人吗", "这个机器人展览挺好玩", "我是学AI的"],
)
def test_detect_suspicion_negative(text: str) -> None:
    """正常内容不应被误判为怀疑。"""

    assert not detect_suspicion(text), text


@pytest.mark.asyncio
async def test_self_improvement_creates_and_updates_files(tmp_path: Path) -> None:
    """SOUL.md / SKILL.md 应被创建，并随反馈更新。"""

    store = SelfImprovementStore(tmp_path, _StubLogger())

    assert store.soul_path.exists()
    assert store.skill_path.exists()

    await store.record_outcome(ChatOutcome(chat_id="g1", text="今天挺累的", got_reply=True))
    await store.record_outcome(
        ChatOutcome(
            chat_id="g1",
            text="作为一个助手我建议你",
            suspected=True,
            suspicion_text="你是不是机器人",
        )
    )

    skill_text = store.skill_path.read_text(encoding="utf-8")
    assert "累计发言：2" in skill_text
    assert "被怀疑是机器人：1" in skill_text
    assert "作为一个助手我建议你" in skill_text
    assert "你是不是机器人" in skill_text

    stats = store.get_stats()
    assert stats["total_messages"] == 2
    assert stats["suspected"] == 1
    assert stats["got_reply"] == 1


@pytest.mark.asyncio
async def test_self_improvement_prompt_block_warns_about_avoid_phrases(tmp_path: Path) -> None:
    """被怀疑过的表达必须进入 prompt 警告块。"""

    store = SelfImprovementStore(tmp_path, _StubLogger())
    await store.record_outcome(
        ChatOutcome(
            chat_id="g1",
            text="很高兴为您服务",
            suspected=True,
            suspicion_text="你是AI吧",
        )
    )

    block = store.build_prompt_block()

    assert "很高兴为您服务" in block
    assert "不要再这么说" in block


@pytest.mark.asyncio
async def test_prompt_block_excludes_human_facing_meta_text(tmp_path: Path) -> None:
    """SOUL.md 里写给人看的说明文字不得混进 prompt。

    否则模型会把"这份文件描述本账号的身份"当成人设的一部分。
    """

    store = SelfImprovementStore(tmp_path, _StubLogger())
    await store.record_outcome(ChatOutcome(chat_id="g1", text="嗯", got_reply=True))

    block = store.build_prompt_block()

    assert "这份文件" not in block
    assert "你可以直接手工编辑" not in block
    assert "句子短" in block, "真正的说话习惯应保留"


@pytest.mark.asyncio
async def test_prompt_experience_file_is_exported(tmp_path: Path) -> None:
    """经验必须导出到主程序约定读取的文件。"""

    store = SelfImprovementStore(tmp_path, _StubLogger())
    await store.record_outcome(
        ChatOutcome(
            chat_id="g1",
            text="有什么可以帮您的吗",
            suspected=True,
            suspicion_text="机器人吧",
        )
    )

    exported = tmp_path / "prompt_experience.txt"

    assert exported.is_file(), "未导出 prompt 经验文件"
    assert "有什么可以帮您的吗" in exported.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_self_improvement_state_persists(tmp_path: Path) -> None:
    """统计状态应跨实例持久化。"""

    store = SelfImprovementStore(tmp_path, _StubLogger())
    await store.record_outcome(ChatOutcome(chat_id="g1", text="test", got_reply=True))

    reloaded = SelfImprovementStore(tmp_path, _StubLogger())

    assert reloaded.get_stats()["total_messages"] == 1


def test_self_improvement_disabled_is_noop(tmp_path: Path) -> None:
    """关闭后不应创建任何文件。"""

    store = SelfImprovementStore(tmp_path / "off", _StubLogger(), enabled=False)

    assert not store.enabled
    assert store.build_prompt_block() == ""


# ---------------------------------------------------------------------------
# 聊天名单过滤
# ---------------------------------------------------------------------------


def _check_group(config: TelegramUserChatConfig, chat_id: str) -> bool:
    """用给定配置判断某个群消息是否放行。

    Args:
        config: 聊天名单配置。
        chat_id: 群 ID。

    Returns:
        bool: 放行返回 ``True``。
    """

    return TelegramUserChatFilter(_StubLogger()).check_allow(
        config,
        user_id="12345",
        chat_id=chat_id,
        is_private=False,
        is_channel=False,
        sender_is_bot=False,
    )


def test_default_config_chats_in_all_groups() -> None:
    """默认配置必须对所有群放行。

    需求要求"对所有群组都执行聊天行为"。若空白名单被当作
    "全部拒绝"，默认配置下一个群都不会聊，功能等于没实现。
    """

    config = TelegramUserChatConfig()

    assert _check_group(config, "-1001234567890"), "默认配置下群消息被丢弃"
    assert _check_group(config, "-100987654321")


def test_non_empty_whitelist_still_restricts() -> None:
    """一旦填了白名单，就只聊名单内的群。"""

    config = TelegramUserChatConfig(group_list_type="whitelist", group_list=["-1001111111111"])

    assert _check_group(config, "-1001111111111")
    assert not _check_group(config, "-1002222222222")


def test_group_blacklist_blocks_listed_group() -> None:
    """黑名单模式下应拦截名单内的群。"""

    config = TelegramUserChatConfig(group_list_type="blacklist", group_list=["-1003333333333"])

    assert not _check_group(config, "-1003333333333")
    assert _check_group(config, "-1004444444444")


def test_private_whitelist_stays_strict() -> None:
    """私聊白名单保持严格：默认不回复陌生人私信。

    需求只要求"所有群组"，私聊放开会让账号有求必应地回应任何陌生人，
    这既不像真人，也是风控高危行为。
    """

    config = TelegramUserChatConfig()
    allowed = TelegramUserChatFilter(_StubLogger()).check_allow(
        config,
        user_id="99999",
        chat_id="99999",
        is_private=True,
        is_channel=False,
        sender_is_bot=False,
    )

    assert not allowed, "默认不应回复未在白名单的私聊"


def test_banned_user_blocked_even_in_open_group() -> None:
    """全局黑名单用户即使在放开的群里也应被拦截。"""

    config = TelegramUserChatConfig(ban_user_id=["12345"])

    assert not _check_group(config, "-1001234567890")


def test_group_chat_can_be_disabled_entirely() -> None:
    """总开关关闭后不参与任何群聊，优先级高于名单。

    空名单被定义为"不限制"，因此需要独立开关才能完全退出群聊。
    """

    config = TelegramUserChatConfig(enable_group_chat=False)

    assert not _check_group(config, "-1001234567890")
    assert not _check_group(config, "-100987654321")


def test_disabled_group_chat_overrides_explicit_whitelist() -> None:
    """即使群号在白名单里，总开关关闭也不参与。"""

    config = TelegramUserChatConfig(
        enable_group_chat=False,
        group_list_type="whitelist",
        group_list=["-1001111111111"],
    )

    assert not _check_group(config, "-1001111111111")


def test_disabling_group_chat_does_not_affect_private() -> None:
    """关闭群聊不应影响白名单内的私聊。"""

    config = TelegramUserChatConfig(enable_group_chat=False, private_list=["1000000002"])
    allowed = TelegramUserChatFilter(_StubLogger()).check_allow(
        config,
        user_id="1000000002",
        chat_id="1000000002",
        is_private=True,
        is_channel=False,
        sender_is_bot=False,
    )

    assert allowed, "关闭群聊不应波及私聊"


# ---------------------------------------------------------------------------
# 在线状态
# ---------------------------------------------------------------------------


class _FakeTelethonClient:
    """记录 UpdateStatusRequest 调用的假 Telethon client。"""

    def __init__(self) -> None:
        self.calls: list[bool] = []

    async def __call__(self, request: object) -> bool:
        self.calls.append(bool(request.offline))
        return True


class _FakeTgClient:
    """只暴露 client 属性的假 TelegramUserClient。"""

    def __init__(self) -> None:
        self.client = _FakeTelethonClient()


@pytest.mark.asyncio
async def test_presence_reports_online_then_offline() -> None:
    """应先上报在线，最终上报离线。"""

    tg = _FakeTgClient()
    presence = PresenceManager(tg, _StubLogger())

    await presence.go_online()
    assert presence.is_online
    assert tg.client.calls == [False]

    await presence.force_offline()
    assert not presence.is_online
    assert tg.client.calls == [False, True]


@pytest.mark.asyncio
async def test_presence_deduplicates_repeated_online() -> None:
    """重复上线不应重复上报，避免状态抖动被识别。"""

    tg = _FakeTgClient()
    presence = PresenceManager(tg, _StubLogger())

    await presence.go_online()
    await presence.go_online()
    await presence.go_online()

    assert len(tg.client.calls) == 1


@pytest.mark.asyncio
async def test_presence_survives_inverted_linger_config() -> None:
    """linger_min > linger_max 属于配置错误，但不能让发送流程崩溃。"""

    tg = _FakeTgClient()
    presence = PresenceManager(tg, _StubLogger(), linger_min=15.0, linger_max=4.0)

    await presence.go_online()
    await presence.schedule_offline()
    await presence.force_offline()

    assert not presence.is_online


@pytest.mark.asyncio
async def test_presence_handles_missing_client() -> None:
    """client 尚未建立时不应抛异常。"""

    class _NoClient:
        client = None

    presence = PresenceManager(_NoClient(), _StubLogger())

    await presence.go_online()
    await presence.force_offline()

    assert not presence.is_online
