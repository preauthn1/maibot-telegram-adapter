"""私有名单限定的频率实验；不影响身份、来源、内容与权限防护。

名单位于 data/frequency_test_targets.json，格式为 {"targets": ["会话键"]}。
只精确匹配，不展开群/话题别名。旧的全局环境开关不再授权插件豁免。
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from inspect import signature
from pathlib import Path
from typing import Iterator, Optional

import json

_TARGET_FILE = Path(__file__).resolve().parents[2] / "data" / "frequency_test_targets.json"
_current_chat: ContextVar[Optional[str]] = ContextVar("frequency_test_chat", default=None)


def targets() -> frozenset[str]:
    """热读私有名单；文件缺失或损坏时收紧为正常模式。"""
    try:
        data = json.loads(_TARGET_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    if not isinstance(data, dict) or not isinstance(data.get("targets"), list):
        return frozenset()
    values = data["targets"]
    if not all(isinstance(value, str) and value and value == value.strip() for value in values):
        return frozenset()
    return frozenset(values)


def is_unlimited(chat_id: Optional[str] = None) -> bool:
    """显式目标优先，缺省只读取本协程上下文；永不全局放行。"""
    key = str(chat_id) if chat_id is not None else _current_chat.get()
    return bool(key and key in targets())


@contextmanager
def frequency_scope(chat_id: str) -> Iterator[None]:
    """跨 await 隔离会话，异常/取消后也复位。共享 worker 必须重新绑定。"""
    token = _current_chat.set(str(chat_id))
    try:
        yield
    finally:
        _current_chat.reset(token)


def scoped_frequency(parameter: str):
    """为异步入口绑定真实参数，保留 SDK 所需签名与装饰器元数据。"""
    def decorate(function):
        sig = signature(function)
        @wraps(function)
        async def wrapped(*args, **kwargs):
            bound = sig.bind(*args, **kwargs)
            value = bound.arguments[parameter]
            if parameter == "event":
                key = str(value.chat_id)
            elif parameter == "message":
                key = bound.arguments["self"]._resolve_outbound_chat_id(value)
            else:
                key = str(value)
            with frequency_scope(key):
                return await function(*args, **kwargs)
        return wrapped
    return decorate


def describe() -> str:
    """日志不输出私有名单。"""
    return f"目标频率实验：{len(targets())} 个精确会话；其他会话与安全防护保持正常"
