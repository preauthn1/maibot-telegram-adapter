"""出站文本污染检测。

背景：8-30 21:15 账号在某休闲小群发出过 ``假false``——中英混杂的布尔值，
人绝对不会这么打字。9 秒前刚有人问过 "ai？"，这条基本坐实了怀疑。

这类污染来自模型输出泄漏（把内部字段、JSON 片段、角色标记当正文
发出去），一次就足以暴露，因此必须在发送前拦截，而不是靠事后
review 发现。

设计取舍：
- 协议/格式泄漏（`_POLLUTION_PATTERNS`）在群聊和私聊全局拦截；
- 群友身份/客服套话/模态失明暴露/代作者审Bug（`_GROUP_ONLY_PATTERNS`）仅在 `is_group_chat=True` 时生效，
  且自动剥离成对引号与第三人称转述分句（如 `他说发截图吧`、`「视频看不到」`），防止私聊或转述引用误杀。
"""

from __future__ import annotations

from typing import List, Tuple

import re
import json

# 剥离成对引号内容及第三人称转述分句（含引导词后的被转述子句），避免转述他人原话时被误判为机器人自身话术。
_INDIRECT_QUOTE_RE = re.compile(
    r'「[^」]*」|“[^”]*”|"[^"]*"|『[^』]*』|\x27[^\x27]*\x27|'
    r'(?:他|她|对方|群友|有人|别人|楼主)(?:刚刚|刚才|不是)?(?:说|问|发了|回|提到)[:：，,\s]*[^，,。！!？?；;\n]*'
)

# 全局协议/格式泄漏：无论群聊或私聊一律拦截。
_POLLUTION_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"[\u4e00-\u9fff](?:false|true|none|null|nan|undefined)\b", "中英混杂字面量"),
    (r"\b(?:false|true|none|null|nan|undefined)[\u4e00-\u9fff]", "中英混杂字面量"),
    (r"^\s*(?:assistant|user|system)\s*[:：]", "角色标记泄漏"),
    (r"<\|.*?\|>", "特殊 token 泄漏"),
    (r"^\s*(?:思考|推理|Thought|Reasoning)\s*[:：]", "思维链泄漏"),
    (r"^\s*分析\s*[:：]\s*(?:用户|对方|他|她|这条|这句|我应该|我需要|应该回复|需要回复)", "思维链泄漏"),
    (r"</?(?:tool_call|arg_value)(?:\s[^>]*)?>", "工具协议残片"),
    (r"久久精品", "异常尾缀污染"),
)
_COMPILED = tuple((re.compile(p, re.I), label) for p, label in _POLLUTION_PATTERNS)

# 群聊专属角色/客服/模态失明边界（私聊不启用，且先剥离转述/引用后匹配）。
_GROUP_ONLY_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"3\s*\+\s*6\s*=\s*9.{0,12}9\.(?:8|11)", "多道测试题合并作答"),
    (r"神秘\s*mcp", "内部实现变相认领"),
    (r"^问.{1,15}(?:能装|怎么|是不是).*[？?]$", "内部分析摘要残留"),
    (r"我检查一?下.{0,12}(?:显示|逻辑|状态|代码|实现|按钮|配置|布局)", "冒充项目开发者认领"),
    (r"收到[，,\s]*(?:字号|字体|界面|按钮|底栏|间距|我再|马上改|后面改)", "冒充项目开发者认领"),
    (r"后面补上.{0,10}(?:中文|说明|文档|版本|功能)", "冒充项目开发者认领"),
    (r"(?:细节|界面|这边)还会继续打磨|先把(?:界面|底栏)打磨|改好发图行|再调底栏", "冒充项目开发者认领"),
    (r"(?:具体哪里不对|什么问题)[？?，,\s]*发(?:下|个)?截图看看", "客服索图套话"),
    (r"那就好[，,\s]*(?:安装成功|搞定|解决|能用)了", "客服结单套话"),
    (r"发来我(?:可以)?(?:帮你看看|瞅瞅|研究研究)|(?:看不清|截图看不清)[，,\s]*发下(?:文件名|客户端名)", "客服索图揽活套话"),
    (r"^(?:我这边|这边|我)?(?:你发的)?(?:视频|画面|图片|截图|图|具体内容|html内容|HTML内容).{0,4}(?:我这边|这边|我)?(?:看不到|没看到|看不见|看不了)(?:[，,\s]|$)|^(?:我这边|这边|我)?(?:看不到|没看到|看不见|看不了)(?:你发的)?(?:视频|画面|图片|截图|图|具体内容|html内容|HTML内容)", "模态失明暴露话术"),
    (r"^(?:(?:视频|图片|截图).{0,6})?(?:发|截|补)(?:个|下|一下|一张)?截图(?:吧|看看|来看看)|^截(?:一下)?你卡住的(?:页面|地方|那一步)|^就是你卡住的(?:检测)?页面|^视频里(?:具体)?卡(?:在)?哪(?:一)?步", "客服索图与盲猜视频话术"),
    (r"^(?:暂时|目前)?(?:查不到|没查到|没有查到|搜不到|没搜到).{1,12}$", "主动汇报搜索失败机器腔"),
    (r"复现步骤已经写全了.{0,12}(?:日志|定位)", "冒充维护者审阅Bug报告"),
    (r"(?:暂时|目前)?(?:还)?(?:不能|无法|没法)确认(?:哪个是|是否为|是不是)?官方|不代表真实(?:使用)?情况|有两个说法\s*[：:]", "AI检索免责或汇总列表腔"),
)
_GROUP_ONLY_COMPILED = tuple((re.compile(p, re.I), label) for p, label in _GROUP_ONLY_PATTERNS)


def strip_indirect_quotes(text: str) -> str:
    """剥离成对引号与第三人称转述分句，仅保留当前发言者自身表态。"""
    return _INDIRECT_QUOTE_RE.sub("", text or "").strip()


def detect_pollution(text: str, *, is_group_chat: bool = True) -> Tuple[bool, List[str]]:
    """检查出站文本是否含有模型泄漏痕迹或群聊越界话术。"""
    normalized = (text or "").strip()
    if not normalized:
        return False, []

    valid_json = False
    if normalized.startswith(('{', '[')):
        try:
            valid_json = isinstance(json.loads(normalized), (dict, list))
        except (ValueError, RecursionError):
            pass

    reasons: List[str] = []
    for pattern, label in _COMPILED:
        if valid_json and label in ('JSON 片段', '疑似 JSON 对象'):
            continue
        if pattern.search(normalized):
            reasons.append(label)

    if is_group_chat:
        unquoted = strip_indirect_quotes(normalized)
        if unquoted:
            for pattern, label in _GROUP_ONLY_COMPILED:
                if pattern.search(unquoted):
                    reasons.append(label)

    return bool(reasons), reasons


def is_safe_to_send(text: str, *, is_group_chat: bool = True) -> bool:
    """判断文本是否可以安全发出。"""
    polluted, _ = detect_pollution(text, is_group_chat=is_group_chat)
    return not polluted
