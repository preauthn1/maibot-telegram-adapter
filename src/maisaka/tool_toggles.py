"""内置工具的环境变量开关。

## 为什么需要

2026-09-04 15:17：群友问"图在哪？"，Planner 调用 ``send_image`` 把
5 分钟前别人发的科普图原样重发。真人会说"往上翻"，不会把别人的图
复读一遍——图片二进制完全一致，原作者就在群里。

这不是 ``send_image`` 的 bug，是它**存在**就是问题：只要模型选中它，
行为就必然不像人。同理还有 ``send_emoji``（发表情包图片）等，
不同部署场景对"哪些工具该露给模型"的判断不同，需要能在部署层面关掉。

## 为什么用环境变量

- 生产由 systemd 管理，``TG_UNLIMITED_MODE`` 等开关已在单元文件里，
  同一处维护，不用再翻 toml
- bot_config.toml 被 gitignore，且按项目规范改配置要走模版+版本号
- 环境变量在进程启动时固定，不会被 file_watcher 热重载撞掉

## 用法

    MAISAKA_DISABLED_TOOLS=send_image                 # 禁一个
    MAISAKA_DISABLED_TOOLS=send_image,send_emoji      # 禁多个（逗号/空格/分号都行）

写错工具名会在启动时立刻报错，不会静默忽略——否则以为禁了其实没禁，
等下次事故才发现。
"""

import os
import re
from typing import FrozenSet, Optional

ENV_DISABLED_TOOLS = "MAISAKA_DISABLED_TOOLS"

# 逗号、分号、任意空白都当分隔符——systemd Environment= 里写起来随意点
_SEPARATOR_RE = re.compile(r"[,;\s]+")

# 进程内解析一次。环境变量启动后不变，每次构建工具列表都 split 是浪费。
_cache: Optional[FrozenSet[str]] = None


class UnknownToolNameError(ValueError):
    """环境变量里出现了不存在的工具名。"""


def _parse(raw: str, known: FrozenSet[str]) -> FrozenSet[str]:
    """把原始字符串解析成工具名集合，并校验每个名字。

    Args:
        raw: 环境变量原始值。
        known: 全部合法工具名。

    Returns:
        FrozenSet[str]: 去重、小写化后的禁用集合。

    Raises:
        UnknownToolNameError: 含有不在 ``known`` 里的名字。
    """

    names = frozenset(
        token.lower() for token in _SEPARATOR_RE.split(raw.strip()) if token
    )
    unknown = names - known
    if unknown:
        raise UnknownToolNameError(
            f"{ENV_DISABLED_TOOLS} 含未知工具名 {sorted(unknown)}；"
            f"合法名字：{sorted(known)}"
        )
    return names


def get_disabled_tools(*, known: FrozenSet[str]) -> FrozenSet[str]:
    """返回被环境变量禁用的内置工具名集合。

    Args:
        known: 全部合法工具名，用于校验拼写。

    Returns:
        FrozenSet[str]: 禁用集合；未设置或为空时返回空集。
    """

    global _cache
    if _cache is None:
        _cache = _parse(os.environ.get(ENV_DISABLED_TOOLS, ""), known)
    return _cache


def is_tool_disabled(name: str, *, known: FrozenSet[str]) -> bool:
    """判断单个工具是否被禁用。"""

    return name.lower() in get_disabled_tools(known=known)


def reset_cache() -> None:
    """清空解析缓存。仅供测试在切换环境变量后调用。"""

    global _cache
    _cache = None


def describe(*, known: FrozenSet[str]) -> str:
    """给启动日志用的一行状态描述。"""

    disabled = get_disabled_tools(known=known)
    if not disabled:
        return f"{ENV_DISABLED_TOOLS} 未设置，内置工具全部可用"
    return f"{ENV_DISABLED_TOOLS} 已禁用内置工具：{sorted(disabled)}"
