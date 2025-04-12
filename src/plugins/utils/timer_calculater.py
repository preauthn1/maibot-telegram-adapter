from time import perf_counter
from functools import wraps
from typing import Optional, Dict, Callable
import asyncio

"""
# 更好的计时器
支持上下文和装饰器
感谢D指导

# 用法：

- 装饰器
time_dict = {}
@Timer("计数", time_dict)
def func():
    pass
print(time_dict)

- 上下文_1
def func():
    with Timer() as t:
        pass
    print(t)
    print(t.human_readable)    

- 上下文_2
def func():
    time_dict = {}
    with Timer("计数", time_dict):
        pass
    print(time_dict)

参数：
- name：计时器的名字，默认为None
- time_dict：计时器结果存储字典，默认为None
- auto_unit： 自动选择单位（为毫秒或秒/一直为秒），默认为True（为毫秒或秒）

属性：human_readable

自定义错误：TimerTypeError
"""


class TimerTypeError(TypeError):
    """自定义类型错误"""

    def __init__(self, param, expected_type, actual_type):
        super().__init__(f"参数 '{param}' 类型错误，期望 {expected_type}，实际得到 {actual_type.__name__}")


class Timer:
    """支持上下文+装饰器的计时器"""

    def __init__(self, name: Optional[str] = None, storage: Optional[Dict[str, float]] = None, auto_unit: bool = True):
        self._validate_types(name, storage)

        self.name = name
        self.storage = storage
        self.elapsed = None
        self.auto_unit = auto_unit
        self._is_context = False

    def _validate_types(self, name, storage):
        """类型检查"""
        if name is not None and not isinstance(name, str):
            raise TimerTypeError("name", "Optional[str]", type(name))

        if storage is not None and not isinstance(storage, dict):
            raise TimerTypeError("storage", "Optional[dict]", type(storage))

    def __call__(self, func: Optional[Callable] = None) -> Callable:
        """装饰器模式"""
        if func is None:
            return lambda f: Timer(name=self.name or f.__name__, storage=self.storage, auto_unit=self.auto_unit)(f)

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            with self:
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            with self:
                return func(*args, **kwargs)

        wrapper = async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
        wrapper.__timer__ = self  # 保留计时器引用
        return wrapper

    def __enter__(self):
        """上下文管理器入口"""
        self._is_context = True
        self.start = perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed = perf_counter() - self.start
        self._record_time()
        self._is_context = False
        return False

    def _record_time(self):
        """记录时间"""
        if self.storage is not None and self.name:
            self.storage[self.name] = self.elapsed

    @property
    def human_readable(self) -> str:
        """人类可读时间格式"""
        if self.elapsed is None:
            return "未计时"

        if self.auto_unit:
            return f"{self.elapsed * 1000:.2f}毫秒" if self.elapsed < 1 else f"{self.elapsed:.2f}秒"
        return f"{self.elapsed:.4f}秒"

    def __str__(self):
        return f"<Timer {self.name or '匿名'} [{self.human_readable}]>"
