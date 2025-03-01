from typing import Union, List, Optional, Deque, Dict
from nonebot.adapters.onebot.v11 import Bot, MessageSegment
import asyncio
import random
import os
from .message import Message, Message_Thinking, MessageSet
from .cq_code import CQCode
from collections import deque
import time
from .storage import MessageStorage 
from .config import global_config
from .cq_code import cq_code_tool

if os.name == "nt":
    from .message_visualizer import message_visualizer
    


class SendTemp:
    """单个群组的临时消息队列管理器"""
    def __init__(self, group_id: int, max_size: int = 100):
        self.group_id = group_id
        self.max_size = max_size
        self.messages: Deque[Union[Message, Message_Thinking]] = deque(maxlen=max_size)
        self.last_send_time = 0
        
    def add(self, message: Message) -> None:
        """按时间顺序添加消息到队列"""
        if not self.messages:
            self.messages.append(message)
            return
        
        # 按时间顺序插入
        if message.time >= self.messages[-1].time:
            self.messages.append(message)
            return

        # 使用二分查找找到合适的插入位置
        messages_list = list(self.messages)
        left, right = 0, len(messages_list)

        while left < right:
            mid = (left + right) // 2
            if messages_list[mid].time < message.time:
                left = mid + 1
            else:
                right = mid

        # 重建消息队列，保持时间顺序
        new_messages = deque(maxlen=self.max_size)
        new_messages.extend(messages_list[:left])
        new_messages.append(message)
        new_messages.extend(messages_list[left:])
        self.messages = new_messages
    def get_earliest_message(self) -> Optional[Message]:
        """获取时间最早的消息"""
        message = self.messages.popleft() if self.messages else None
        return message

    def clear(self) -> None:
        """清空队列"""
        self.messages.clear()
        
    def get_all(self, group_id: Optional[int] = None) -> List[Union[Message, Message_Thinking]]:
        """获取所有待发送的消息"""
        if group_id is None:
            return list(self.messages)
        return [msg for msg in self.messages if msg.group_id == group_id]
    
    def peek_next(self) -> Optional[Union[Message, Message_Thinking]]:
        """查看下一条要发送的消息（不移除）"""
        return self.messages[0] if self.messages else None
    
    def has_messages(self) -> bool:
        """检查是否有待发送的消息"""
        return bool(self.messages)
    
    def count(self, group_id: Optional[int] = None) -> int:
        """获取待发送消息数量"""
        if group_id is None:
            return len(self.messages)
        return len([msg for msg in self.messages if msg.group_id == group_id])
    
    def get_last_send_time(self) -> float:
        """获取最后一次发送时间"""
        return self.last_send_time
    
    def update_send_time(self):
        """更新最后发送时间"""
        self.last_send_time = time.time()

class SendTempContainer:
    """管理所有群组的消息缓存容器"""
    def __init__(self):
        self.temp_queues: Dict[int, SendTemp] = {}
        
    def get_queue(self, group_id: int) -> SendTemp:
        """获取或创建群组的消息队列"""
        if group_id not in self.temp_queues:
            self.temp_queues[group_id] = SendTemp(group_id)
        return self.temp_queues[group_id]
    
    def add_message(self, message: Message) -> None:
        """添加消息到对应群组的队列"""
        queue = self.get_queue(message.group_id)
        queue.add(message)
    
    def get_group_messages(self, group_id: int) -> List[Union[Message, Message_Thinking]]:
        """获取指定群组的所有待发送消息"""
        queue = self.get_queue(group_id)
        return queue.get_all()
    
    def has_messages(self, group_id: int) -> bool:
        """检查指定群组是否有待发送消息"""
        queue = self.get_queue(group_id)
        return queue.has_messages()
    
    def get_all_groups(self) -> List[int]:
        """获取所有有待发送消息的群组ID"""
        return list(self.temp_queues.keys())

    def update_thinking_message(self, message_obj: Union[Message, MessageSet]) -> bool:
        queue = self.get_queue(message_obj.group_id)
        # 使用列表解析找到匹配的消息索引
        matching_indices = [
            i for i, msg in enumerate(queue.messages) 
            if msg.message_id == message_obj.message_id
        ]
        
        if not matching_indices:
            return False
            
        index = matching_indices[0]  # 获取第一个匹配的索引

            # 将消息转换为列表以便修改
        messages = list(queue.messages)
        
        # 根据消息类型处理
        if isinstance(message_obj, MessageSet):
            messages.pop(index)
            # 在原位置插入新消息组
            for i, single_message in enumerate(message_obj.messages):
                messages.insert(index + i, single_message)
                # print(f"\033[1;34m[调试]\033[0m 添加消息组中的第{i+1}条消息: {single_message}")
        else:
            # 直接替换原消息
            messages[index] = message_obj
            # print(f"\033[1;34m[调试]\033[0m 已更新消息: {message_obj}")
        
        # 重建队列
        queue.messages.clear()
        for msg in messages:
            queue.messages.append(msg)
            
        return True


class MessageSendControl:
    """消息发送控制器"""
    def __init__(self):
        self.typing_speed = (0.1, 0.3)  # 每个字符的打字时间范围(秒)
        self.message_interval = (0.5, 1)  # 多条消息间的间隔时间范围(秒)
        self.max_retry = 3  # 最大重试次数
        self.send_temp_container = SendTempContainer()
        self._running = True
        self._paused = False
        self._current_bot = None
        self.storage = MessageStorage()  # 添加存储实例
        try:
            message_visualizer.start()
        except(NameError):
            pass
        
    def set_bot(self, bot: Bot):
        """设置当前bot实例"""
        self._current_bot = bot
        
    async def process_group_messages(self, group_id: int):
        queue = self.send_temp_container.get_queue(group_id)
        if queue.has_messages():
            message = queue.peek_next()
            # 处理消息的逻辑
            if isinstance(message, Message_Thinking):
                message.update_thinking_time()
                thinking_time = message.thinking_time
                if thinking_time < 90:  # 最少思考2秒
                    if int(thinking_time) % 15 == 0:
                        print(f"\033[1;34m[调试]\033[0m 消息正在思考中，已思考{thinking_time:.1f}秒")
                    return
                else:
                    print(f"\033[1;34m[调试]\033[0m 思考消息超时，移除")
                    queue.get_earliest_message()  # 移除超时的思考消息
                    return
            elif isinstance(message, Message):
                message = queue.get_earliest_message()
                if message and message.processed_plain_text:
                    print(f"- 群组: {group_id} - 内容: {message.processed_plain_text}")
                    cost_time = round(time.time(), 2) - message.time
                    if cost_time > 40:
                        message.processed_plain_text = cq_code_tool.create_reply_cq(message.message_based_id) + message.processed_plain_text
                    cur_time = time.time()
                    await self._current_bot.send_group_msg(
                        group_id=group_id,
                        message=str(message.processed_plain_text),
                        auto_escape=False
                    )
                    cost_time = round(time.time(), 2) - cur_time
                    print(f"\033[1;34m[调试]\033[0m 消息发送时间: {cost_time}秒")
                    current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(message.time))
                    print(f"\033[1;32m群 {group_id} 消息, 用户 {global_config.BOT_NICKNAME}, 时间: {current_time}:\033[0m {str(message.processed_plain_text)}")
                    await self.storage.store_message(message, None)
                    queue.update_send_time()
                    if queue.has_messages():
                        await asyncio.sleep(
                            random.uniform(
                                self.message_interval[0],
                                self.message_interval[1]
                            )
                        )

    async def start_processor(self, bot: Bot):
        """启动消息处理器"""
        self._current_bot = bot
        
        while self._running:
            await asyncio.sleep(1.5)
            tasks = []
            for group_id in self.send_temp_container.get_all_groups():
                tasks.append(self.process_group_messages(group_id))
            
            # 并行处理所有群组的消息
            await asyncio.gather(*tasks)
            try:
                message_visualizer.update_content(self.send_temp_container)
            except(NameError):
                pass

    def set_typing_speed(self, min_speed: float, max_speed: float):
        """设置打字速度范围"""
        self.typing_speed = (min_speed, max_speed)

# 创建全局实例
message_sender = MessageSendControl()
