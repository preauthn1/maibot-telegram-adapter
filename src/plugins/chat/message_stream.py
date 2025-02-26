from typing import List, Optional, Dict
from .message import Message
import time
from collections import deque
from datetime import datetime, timedelta
import os
import json
import asyncio

class MessageStream:
    """单个群组的消息流容器"""
    def __init__(self, group_id: int, max_size: int = 1000):
        self.group_id = group_id
        self.messages = deque(maxlen=max_size)
        self.max_size = max_size
        self.last_save_time = time.time()
        
        # 确保日志目录存在
        self.log_dir = os.path.join("log", str(self.group_id))
        os.makedirs(self.log_dir, exist_ok=True)
        
        # 启动自动保存任务
        asyncio.create_task(self._auto_save())
    
    async def _auto_save(self):
        """每30秒自动保存一次消息记录"""
        while True:
            await asyncio.sleep(30)  # 等待30秒
            await self.save_to_log()
    
    async def save_to_log(self):
        """将消息保存到日志文件"""
        try:
            current_time = time.time()
            # 只有有新消息时才保存
            if not self.messages or self.last_save_time == current_time:
                return
                
            # 生成日志文件名 (使用当前日期)
            date_str = time.strftime("%Y-%m-%d", time.localtime(current_time))
            log_file = os.path.join(self.log_dir, f"chat_{date_str}.log")
            
            # 获取需要保存的新消息
            new_messages = [
                msg for msg in self.messages
                if msg.time > self.last_save_time
            ]
            
            if not new_messages:
                return
                
            # 将消息转换为可序列化的格式
            message_logs = []
            for msg in new_messages:
                message_logs.append({
                    "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(msg.time)),
                    "user_id": msg.user_id,
                    "user_nickname": msg.user_nickname,
                    "message_id": msg.message_id,
                    "raw_message": msg.raw_message,
                    "processed_text": msg.processed_plain_text
                })
            
            # 追加写入日志文件
            with open(log_file, "a", encoding="utf-8") as f:
                for log in message_logs:
                    f.write(json.dumps(log, ensure_ascii=False) + "\n")
            
            self.last_save_time = current_time
            
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 保存群 {self.group_id} 的消息日志失败: {str(e)}")
    
    def add_message(self, message: Message) -> None:
        """按时间顺序添加新消息到队列
        
        使用改进的二分查找算法来保持消息的时间顺序，同时优化内存使用。
        
        Args:
            message: Message对象，要添加的新消息
        """

        # 空队列或消息应该添加到末尾的情况
        if (not self.messages or 
            message.time >= self.messages[-1].time):
            self.messages.append(message)
            return
            
        # 消息应该添加到开头的情况
        if message.time <= self.messages[0].time:
            self.messages.appendleft(message)
            return
            
        # 使用二分查找在现有队列中找到合适的插入位置
        left, right = 0, len(self.messages) - 1
        while left <= right:
            mid = (left + right) // 2
            if self.messages[mid].time < message.time:
                left = mid + 1
            else:
                right = mid - 1

        temp = list(self.messages)
        temp.insert(left, message)
        
        # 如果超出最大长度，移除多余的消息
        if len(temp) > self.max_size:
            temp = temp[-self.max_size:]
            
        # 重建队列
        self.messages = deque(temp, maxlen=self.max_size)
    
    async def get_recent_messages_from_db(self, count: int = 10) -> List[Message]:
        """从数据库中获取最近的消息记录
        
        Args:
            count: 需要获取的消息数量
            
        Returns:
            List[Message]: 最近的消息列表
        """
        try:
            from ...common.database import Database
            db = Database.get_instance()
            
            # 从数据库中查询最近的消息
            recent_messages = list(db.db.messages.find(
                {"group_id": self.group_id},
                {
                    "time": 1,
                    "user_id": 1,
                    "user_nickname": 1,
                    "message_id": 1,
                    "raw_message": 1,
                    "processed_text": 1
                }
            ).sort("time", -1).limit(count))
            
            if not recent_messages:
                return []
                
            # 转换为 Message 对象
            from .message import Message
            messages = []
            for msg_data in recent_messages:
                msg = Message(
                    time=msg_data["time"],
                    user_id=msg_data["user_id"],
                    user_nickname=msg_data.get("user_nickname", ""),
                    message_id=msg_data["message_id"],
                    raw_message=msg_data["raw_message"],
                    processed_plain_text=msg_data.get("processed_text", ""),
                    group_id=self.group_id
                )
                messages.append(msg)
            
            return list(reversed(messages))  # 返回按时间正序的消息
            
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 从数据库获取群 {self.group_id} 的最近消息记录失败: {str(e)}")
            return []
            
    def get_recent_messages(self, count: int = 10) -> List[Message]:
        """获取最近的n条消息（从内存队列）"""
        print(f"\033[1;34m[调试]\033[0m 从内存获取群 {self.group_id} 的最近{count}条消息记录")
        return list(self.messages)[-count:]
    
    def get_messages_in_timerange(self, 
                                start_time: Optional[float] = None,
                                end_time: Optional[float] = None) -> List[Message]:
        """获取时间范围内的消息"""
        if start_time is None:
            start_time = time.time() - 3600
        if end_time is None:
            end_time = time.time()
            
        return [
            msg for msg in self.messages
            if start_time <= msg.time <= end_time
        ]
    
    def get_user_messages(self, user_id: int, count: int = 10) -> List[Message]:
        """获取特定用户的最近消息"""
        user_messages = [msg for msg in self.messages if msg.user_id == user_id]
        return user_messages[-count:]
    
    def clear_old_messages(self, hours: int = 24) -> None:
        """清理旧消息"""
        cutoff_time = time.time() - (hours * 3600)
        self.messages = deque(
            [msg for msg in self.messages if msg.time > cutoff_time],
            maxlen=self.max_size
        )

class MessageStreamContainer:
    """管理所有群组的消息流容器"""
    def __init__(self, max_size: int = 1000):
        self.streams: Dict[int, MessageStream] = {}
        self.max_size = max_size
    
    async def save_all_logs(self):
        """保存所有群组的消息日志"""
        for stream in self.streams.values():
            await stream.save_to_log()
    
    def add_message(self, message: Message) -> None:
        """添加消息到对应群组的消息流"""
        if not message.group_id:
            return
            
        if message.group_id not in self.streams:
            self.streams[message.group_id] = MessageStream(message.group_id, self.max_size)
        
        self.streams[message.group_id].add_message(message)
    
    def get_stream(self, group_id: int) -> Optional[MessageStream]:
        """获取特定群组的消息流"""
        return self.streams.get(group_id)
    
    def get_all_streams(self) -> Dict[int, MessageStream]:
        """获取所有群组的消息流"""
        return self.streams
    
    def clear_old_messages(self, hours: int = 24) -> None:
        """清理所有群组的旧消息"""
        for stream in self.streams.values():
            stream.clear_old_messages(hours)
    
    def get_group_stats(self, group_id: int) -> Dict:
        """获取群组的消息统计信息"""
        stream = self.streams.get(group_id)
        if not stream:
            return {
                "total_messages": 0,
                "unique_users": 0,
                "active_hours": [],
                "most_active_user": None
            }
            
        messages = stream.messages
        user_counts = {}
        hour_counts = {}
        
        for msg in messages:
            user_counts[msg.user_id] = user_counts.get(msg.user_id, 0) + 1
            hour = datetime.fromtimestamp(msg.time).hour
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
        
        most_active_user = max(user_counts.items(), key=lambda x: x[1])[0] if user_counts else None
        active_hours = sorted(
            hour_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]
        
        return {
            "total_messages": len(messages),
            "unique_users": len(user_counts),
            "active_hours": active_hours,
            "most_active_user": most_active_user
        }

# 创建全局实例
message_stream_container = MessageStreamContainer()
