from ..person_info import person_info
from src.common.logger import get_module_logger
import asyncio
from dataclasses import dataclass
from .message import MessageRecv
import hashlib
from typing import List, Dict
from dataclasses import dataclass, field

logger = get_module_logger("message_buffer")

@dataclass
class CacheMessages:
    message: MessageRecv 
    cache_determination: asyncio.Event = field(default_factory=asyncio.Event)  # 判断缓冲是否产生结果
    result: str = "U"


class MassageBuffer:
    def __init__(self):
        self.buffer_pool: Dict[str, List[CacheMessages]] = {}
        self.lock = asyncio.Lock()

    def get_person_id_(self, platform:str, user_id:str, group_id:str):
        """获取唯一id"""
        group_id = group_id or "私聊"
        key = f"{platform}_{user_id}_{group_id}"
        return hashlib.md5(key.encode()).hexdigest()

    async def start_caching_messages(self, message:MessageRecv):
        """添加消息并重置缓冲计时器"""
        person_id_ = self.get_person_id_(message.chat_info.platform,
                                             message.chat_info.user_info.user_id,
                                             message.chat_info.group_info.group_id)
        async with self.lock:
            # 清空该用户之前的未处理消息
            if person_id_ in self.buffer_pool:
                for old_msg in self.buffer_pool[person_id_]:
                    if old_msg.result == "U":
                        old_msg.cache_determination.set()
                        old_msg.result = "F"  # 标记旧消息为失败
                        logger.debug(f"被新消息覆盖信息id: {message.message_id}")
            
            # 添加新消息
            cache_msg = CacheMessages(message=message, result="U")
            self.buffer_pool[person_id_] = [cache_msg]  # 只保留最新消息
        
        # 启动3秒缓冲计时器
        asyncio.create_task(self._debounce_processor(person_id_, cache_msg))

    async def _debounce_processor(self, person_id_:str, cache_msg:CacheMessages):
        """等待3秒无新消息"""
        await asyncio.sleep(3)
        
        async with self.lock:
            # 检查消息是否仍未被覆盖
            if (person_id_ in self.buffer_pool and 
                cache_msg in self.buffer_pool[person_id_] and
                cache_msg.result == "U"):
                
                cache_msg.result = "T"  # 标记为成功处理
                cache_msg.cache_determination.set()


    async def query_buffer_result(self, message:MessageRecv) -> bool:
        """查询缓冲结果"""
        person_id_ = self.get_person_id_(message.chat_info.platform,
                                        message.chat_info.user_info.user_id,
                                        message.chat_info.group_info.group_id)
        
        async with self.lock:
            if person_id_ not in self.buffer_pool or not self.buffer_pool[person_id_]:
                return False

            cache_msg = self.buffer_pool[person_id_][-1]  # 获取最新消息
            if cache_msg.message.message_id != message.message_id:
                return False

        try:
            await asyncio.wait_for(cache_msg.cache_determination.wait(), timeout=10)
            return cache_msg.result == "T"
        except asyncio.TimeoutError:
            logger.debug(f"查询超时消息id： {message.message_id}")
            return False




message_buffer = MassageBuffer()