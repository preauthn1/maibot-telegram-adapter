"""命令/代码块完整性保护。

真实事故（2026-09-02 16:41-16:42，某技术交流群）：
  16:41:43 出站  "...yabs就这条curl -sL yabs.sh"
  16:41:53 出站  "|bash解锁测试"          ← 同一条命令被拆成两条发出

后果：别人复制第一条跑不通。技术群里贴命令是高频行为，
真人贴命令会用独立消息或代码块，绝不会把管道符拆到下一条。
这类错误会留下白纸黑字的证据，比"反应太快"更难辩解。

本模块负责三件事：
1. 把被上游拆散的命令段重新合并
2. 命令与中文粘连时补分隔
3. 命令用 Telegram 代码块包裹，保证可复制且不被 Markdown 吃掉字符
"""

import pytest

from plugins.telegram_user_adapter.command_guard import (
    format_command_segments,
    has_command,
    merge_split_commands,
    protect_commands,
    strip_tool_markup,
)


class TestHasCommand:
    """命令特征识别。"""

    @pytest.mark.parametrize(
        "text",
        [
            "curl -sL yabs.sh | bash",
            "bash <(curl -L -s media.is/valuexyz)",
            "docker run -d nginx",
            "wget https://example.com/a.sh",
            "sudo apt install vim",
            "ssh root@1.2.3.4",
        ],
    )
    def test_detects_commands(self, text: str) -> None:
        assert has_command(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "今天天气不错",
            "这个节点延迟挺低的",
            "我也是这么想的哈哈",
            "香港🐔基本都不行",
        ],
    )
    def test_ignores_plain_chat(self, text: str) -> None:
        assert has_command(text) is False


class TestMergeSplitCommands:
    """把被拆散的命令段合并——这是事故的直接成因。"""

    def test_merges_pipe_continuation(self) -> None:
        """复现真实事故：管道符被拆到下一段。"""

        segs = [
            {"type": "text", "data": "yabs就这条curl -sL yabs.sh"},
            {"type": "text", "data": "|bash解锁测试"},
        ]

        merged = merge_split_commands(segs)

        assert len(merged) == 1
        assert "curl -sL yabs.sh |bash" in merged[0]["data"]

    def test_merges_logical_and(self) -> None:
        segs = [
            {"type": "text", "data": "cd /opt"},
            {"type": "text", "data": "&& ls -la"},
        ]

        merged = merge_split_commands(segs)

        assert len(merged) == 1

    def test_merges_unbalanced_paren(self) -> None:
        """括号没闭合说明命令没写完。"""

        segs = [
            {"type": "text", "data": "bash <(curl -L -s example.com"},
            {"type": "text", "data": ") 然后就好了"},
        ]

        merged = merge_split_commands(segs)

        assert len(merged) == 1

    def test_leaves_normal_chat_alone(self) -> None:
        """普通聊天分段不受影响——真人本来就会连发几句短句。"""

        segs = [
            {"type": "text", "data": "那确实"},
            {"type": "text", "data": "我也这么觉得"},
            {"type": "text", "data": "回头试试"},
        ]

        merged = merge_split_commands(segs)

        assert len(merged) == 3

    def test_preserves_non_text_segments(self) -> None:
        """图片等非文本段必须原样保留。"""

        segs = [
            {"type": "text", "data": "看这个"},
            {"type": "image", "data": "xxx"},
        ]

        merged = merge_split_commands(segs)

        assert len(merged) == 2
        assert merged[1]["type"] == "image"


class TestProtectCommands:
    """命令与中文粘连时补分隔。"""

    def test_separates_glued_chinese(self) -> None:
        """复现真实事故：命令尾部紧跟中文，没有任何分隔。"""

        text = "bash <(curl -L -s media.is/valuexyz)下次想自己找就github搜"

        out = protect_commands(text)

        # 命令与中文之间必须有分隔（空格或换行）
        assert ")下次" not in out

    def test_keeps_already_separated(self) -> None:
        text = "跑这个 curl -sL yabs.sh | bash 就行"

        out = protect_commands(text)

        assert "curl -sL yabs.sh | bash" in out

    def test_plain_chat_untouched(self) -> None:
        text = "这个节点延迟挺低的"

        assert protect_commands(text) == text

    def test_does_not_split_chinese_words(self) -> None:
        """不能把中文逐字拆开。

        回归测试：前置断言漏了排除中文时，"找就github" 里每个中文字
        都被当成"命令字符+中文"的边界，整句被拆成 "下 次 想 自 己 找"。
        """

        text = "bash <(curl -L -s media.is/valuexyz)下次想自己找就github搜"

        out = protect_commands(text)

        assert "下次想自己找" in out, f"中文被拆开了: {out!r}"
        assert " 下 次 " not in out


class TestStripToolMarkup:
    """工具调用标记泄漏——最高等级的身份暴露。

    真实事故（2026-09-02 23:00，某技术交流群）：
        出站 "对就这个</arg_value></tool_call>"

    没有任何人类会打出这种字符串，一次就是当场坐实。
    事故当时 rewritten=False、identity_guard_triggered=False，
    说明所有既有防护层都不认识这类标记。
    """

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("对就这个</arg_value></tool_call>", "对就这个"),
            ("好的<tool_call>", "好的"),
            ("试试看</invoke>", "试试看"),
            ("行</parameter></invoke>", "行"),
            ("嗯<|im_end|>", "嗯"),
            ("好</function_call>", "好"),
        ],
    )
    def test_strips_tool_markup(self, raw: str, expected: str) -> None:
        assert strip_tool_markup(raw) == expected

    def test_returns_empty_when_only_markup(self) -> None:
        """整条都是标记时应返回空串，由调用方丢弃整条。"""

        assert strip_tool_markup("</tool_call>").strip() == ""

    @pytest.mark.parametrize(
        "text",
        [
            "这个 3 < 5 对吧",
            "用 -> 表示指向",
            "a<b 这种写法",
            "普通聊天没有标记",
        ],
    )
    def test_keeps_normal_text(self, text: str) -> None:
        """普通文本里的尖括号不能被误删。"""

        assert strip_tool_markup(text) == text

    def test_strips_from_middle(self) -> None:
        out = strip_tool_markup("前面</tool_call>后面")

        assert "tool_call" not in out
        assert "前面" in out and "后面" in out


class TestFormatCommandSegments:
    """代码块包裹 + parse_mode 判定。"""

    def test_wraps_command_in_code_block(self) -> None:
        text = "curl -sL yabs.sh | bash"

        formatted, parse_mode = format_command_segments(text)

        assert "`" in formatted
        assert parse_mode == "md"

    def test_plain_text_no_parse_mode(self) -> None:
        """普通聊天不启用 Markdown。

        这很重要：一旦开了 parse_mode，聊天里的 * _ ` 等字符
        会被当成格式标记吃掉或报错。
        """

        text = "这个* 真的不错_ 哈哈"

        formatted, parse_mode = format_command_segments(text)

        assert formatted == text
        assert parse_mode is None

    def test_does_not_double_wrap(self) -> None:
        """已经是代码块的不再包一层。"""

        text = "```\ncurl -sL yabs.sh | bash\n```"

        formatted, _ = format_command_segments(text)

        assert formatted.count("```") == 2

    def test_command_content_intact(self) -> None:
        """核心保证：命令内容一个字符都不能少。"""

        cmd = "bash <(curl -L -s media.is/valuexyz)"
        formatted, _ = format_command_segments(cmd)

        assert cmd in formatted
