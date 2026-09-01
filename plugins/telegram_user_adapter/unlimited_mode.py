"""极端实验模式：一次性解除全部**频率类**限制。

为什么用环境变量而不是删代码：
删掉的代码要靠 git revert 才能回来，而这是个观察性实验——
随时可能需要立刻收手。开关放在环境变量里，回滚只需去掉
systemd 的 Environment 行并重启，不碰任何逻辑。

⚠️ 本开关只解除频率类限制（发多少、多久发一次）。
身份类防护（22 条泄漏模式、污染检测、发言前自检）**不受影响**，
因为上次真正导致封号的是举报 + 人工审核链路：
群里有人看出不是真人 → 举报 → moderator 确认。
那条路径与发言频率无关，删掉身份防护会让实验直接失去意义
（分不清是"话太多"还是"说了不该说的"导致的后果）。

用法：
    UNLIMITED_MODE=1   解除频率限制
    不设或设为 0        正常模式
"""

import os

_ENV_KEY = "TG_UNLIMITED_MODE"


def is_unlimited() -> bool:
    """是否处于极端实验模式。

    Returns:
        True 表示解除频率类限制。
    """

    return os.environ.get(_ENV_KEY, "").strip() in {"1", "true", "yes", "on"}


def describe() -> str:
    """给日志用的一行状态描述。"""

    if is_unlimited():
        return "⚠️ 极端实验模式：频率类限制已全部解除（身份防护仍生效）"
    return "正常模式：频率限制生效"
