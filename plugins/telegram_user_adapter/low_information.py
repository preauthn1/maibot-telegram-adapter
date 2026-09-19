"""保守识别低信息动作族；按实际成功消息维护全局滑窗。"""
from collections import deque
from typing import Deque, Dict, Tuple
import re


# 仅匹配完整泛化回应，不凭字数判断；数字、命令、型号与技术结论不在此列。
_FAMILY = re.compile(
    r"(?:那|这)?(?:确实|真的|的确)?(?:太贵了|贵了|贵|正常|离谱|夸张|好贵|有点贵)"
    r"|(?:对|对的|是|是的|也是|确实|确实如此|没错|有道理|懂了|明白了|原来如此|好|好的|好吧|行|可以|嗯|嗯嗯|哦|哦哦|哈哈|哈哈哈)"
    r"|(?:那还行(?:能用了)?|也行|都行|行吧|这速度舒服|那确实看着爽)"
)


def is_low_information(text: str) -> bool:
    """白名单完整匹配；保留疑问、否定、代码和技术信息，不做语义推断。

    只忽略聊天分隔符。不能删除全部 Unicode 标点，否则代码引号、路径
    分隔符甚至问号都会丢失。“能用了”单独出现可能是排障结果，仍保留。
    """
    normalized = ''.join(
        char for char in text.strip()
        if not char.isspace() and char not in '，,。！!、；;'
    )
    return _FAMILY.fullmatch(normalized) is not None


class LowInformationGuard:
    def __init__(self, *, window_size: int = 10, limit: int = 2) -> None:
        if window_size < 1 or not 0 <= limit <= window_size:
            raise ValueError('低信息窗口必须为正数，限额须在 0 到窗口大小之间')
        self.limit = limit
        self.window_size = window_size
        self._successes: Deque[bool] = deque(maxlen=window_size)

    def allows(self, text: str) -> bool:
        # 纳入本次成功后的最后 N 条也必须满足上限，因此仅看之前 N-1 条。
        preceding = list(self._successes)[-(self.window_size - 1):] if self.window_size > 1 else []
        return not is_low_information(text) or sum(preceding) < self.limit

    def record(self, text: str) -> None:
        self._successes.append(is_low_information(text))


class LowInformationTargetReservation:
    """短期预占明确引用目标，防止并发泛化回复重复发送。

    这是进程内同步操作：调用点之间没有 ``await``，所以一次 reserve 的
    检查和写入对同一事件循环任务是原子的。成功发送保留至 TTL 到期；失败、
    取消或发送端返回空结果必须显式 release，不能消耗目标名额。
    """

    def __init__(self, *, ttl_seconds: float = 20.0, max_entries: int = 512) -> None:
        if ttl_seconds <= 0 or max_entries < 1:
            raise ValueError('低信息目标预占 TTL 和容量必须为正数')
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._reservations: Dict[Tuple[str, str], float] = {}

    def _prune(self, now: float) -> None:
        expired = [key for key, deadline in self._reservations.items() if deadline <= now]
        for key in expired:
            del self._reservations[key]
        overflow = len(self._reservations) - self._max_entries
        if overflow > 0:
            for key, _ in sorted(self._reservations.items(), key=lambda item: item[1])[:overflow]:
                del self._reservations[key]

    def reserve(self, chat_id: str, target_message_id: str, *, now: float) -> bool:
        """预占明确的 chat/消息目标；已有未到期预占时返回 ``False``。"""
        self._prune(now)
        key = (str(chat_id), str(target_message_id))
        if key in self._reservations:
            return False
        self._reservations[key] = now + self._ttl_seconds
        return True

    def release(self, chat_id: str, target_message_id: str) -> None:
        """仅释放本次失败发送的明确目标预占。"""
        self._reservations.pop((str(chat_id), str(target_message_id)), None)
