from typing import Dict, List, Optional
from dataclasses import dataclass
import time
import threading
import asyncio
from .message import Message
from .storage import MessageStorage
from .topic_identifier import TopicIdentifier
from ...common.database import Database
import random

@dataclass
class Topic:
    id: str
    name: str
    messages: List[Message]
    created_time: float
    last_active_time: float
    message_count: int
    is_active: bool = True
    
class MessageStream:
    def __init__(self):
        self.storage = MessageStorage()
        self.active_topics: Dict[int, List[Topic]] = {}  # group_id -> topics
        self.topic_identifier = TopicIdentifier()
        self.db = Database.get_instance()
        self.topic_lock = threading.Lock()
        
    async def start(self):
        """异步初始化"""
        asyncio.create_task(self._monitor_topics())
        
    async def _monitor_topics(self):
        """定时监控主题状态"""
        while True:
            await asyncio.sleep(30)
            self._print_active_topics()
            self._check_inactive_topics()
            self._remove_small_topic()
            
    def _print_active_topics(self):
        """打印当前活跃主题"""
        print("\n" + "="*50)
        print("\033[1;36m【当前活跃主题】\033[0m")  # 青色
        for group_id, topics in self.active_topics.items():
            active_topics = [t for t in topics if t.is_active]
            if active_topics:
                print(f"\n\033[1;33m群组 {group_id}:\033[0m")  # 黄色
                for topic in active_topics:
                    print(f"\033[1;32m- {topic.name}\033[0m (消息数: {topic.message_count})")  # 绿色
            
    def _check_inactive_topics(self):
        """检查并处理不活跃主题"""
        current_time = time.time()
        INACTIVE_TIME = 600  # 60秒内没有新增内容
        # MAX_MESSAGES_WITHOUT_TOPIC = 5  # 最新5条消息都不是这个主题就归档
        
        with self.topic_lock:
            for group_id, topics in self.active_topics.items():
                
                for topic in topics:
                    if not topic.is_active:
                        continue
                        
                    # 检查是否超过不活跃时间
                    time_inactive = current_time - topic.last_active_time
                    if time_inactive > INACTIVE_TIME:
                        # print(f"\033[1;33m[主题超时]\033[0m {topic.name} 已有 {int(time_inactive)} 秒未更新")
                        self._archive_topic(group_id, topic)
                        topic.is_active = False
                        continue


    def _archive_topic(self, group_id: int, topic: Topic):
        """将主题存档到数据库"""
        # 查找是否有同名主题
        existing_topic = self.db.db.archived_topics.find_one({
            "name": topic.name
        })
        
        if existing_topic:
            # 合并消息列表并去重
            existing_messages = existing_topic.get("messages", [])
            new_messages = [
                {
                    "user_id": msg.user_id,
                    "plain_text": msg.plain_text,
                    "time": msg.time
                } for msg in topic.messages
            ]
            
            # 使用集合去重
            seen_texts = set()
            unique_messages = []
            
            # 先处理现有消息
            for msg in existing_messages:
                if msg["plain_text"] not in seen_texts:
                    seen_texts.add(msg["plain_text"])
                    unique_messages.append(msg)
            
            # 再处理新消息
            for msg in new_messages:
                if msg["plain_text"] not in seen_texts:
                    seen_texts.add(msg["plain_text"])
                    unique_messages.append(msg)
            
            # 更新主题信息
            self.db.db.archived_topics.update_one(
                {"_id": existing_topic["_id"]},
                {
                    "$set": {
                        "messages": unique_messages,
                        "message_count": len(unique_messages),
                        "last_active_time": max(existing_topic["last_active_time"], topic.last_active_time),
                        "last_merged_time": time.time()
                    }
                }
            )
            print(f"\033[1;33m[主题合并]\033[0m 主题 {topic.name} 已合并，总消息数: {len(unique_messages)}")
            
        else:
            # 存储新主题
            self.db.db.archived_topics.insert_one({
                "topic_id": topic.id,
                "name": topic.name,
                "messages": [
                    {
                        "user_id": msg.user_id,
                        "plain_text": msg.plain_text,
                        "time": msg.time
                    } for msg in topic.messages
                ],
                "created_time": topic.created_time,
                "last_active_time": topic.last_active_time,
                "message_count": topic.message_count
            })
            print(f"\033[1;32m[主题存档]\033[0m {topic.name} (群组: {group_id})")
        
    async def process_message(self, message: Message,topic:List[str]):
        """处理新消息，返回识别出的主题列表"""
        # 存储消息（包含主题）
        await self.storage.store_message(message, topic)
        self._update_topics(message.group_id, topic, message)
        
    def _update_topics(self, group_id: int, topic_names: List[str], message: Message) -> None:
        """更新群组主题"""
        current_time = time.time()

        # 确保群组存在
        if group_id not in self.active_topics:
            self.active_topics[group_id] = []
            
        # 查找现有主题
        for topic_name in topic_names:
            for topic in self.active_topics[group_id]:
                if topic.name == topic_name:
                    topic.messages.append(message)
                    topic.last_active_time = current_time
                    topic.message_count += 1
                    print(f"\033[1;35m[更新主题]\033[0m {topic_name}")  # 绿色
                    break
            else:
                # 创建新主题
                new_topic = Topic(
                    id=f"{group_id}_{int(current_time)}",
                    name=topic_name,
                    messages=[message],
                    created_time=current_time,
                    last_active_time=current_time,
                    message_count=1
                )
                self.active_topics[group_id].append(new_topic)

        self._check_inactive_topics() 

    def _remove_small_topic(self):
        """随机移除一个12小时内没有新增内容的小主题"""
        try:
            current_time = time.time()
            inactive_time = 12 * 3600  # 24小时
            
            # 获取所有符合条件的主题
            topics = list(self.db.db.archived_topics.find({
                "message_count": {"$lt": 3},  # 消息数小于2
                "last_active_time": {"$lt": current_time - inactive_time}  
            }))
            
            if not topics:
                return
                
            # 随机选择一个主题删除
            topic_to_remove = random.choice(topics)
            inactive_hours = (current_time - topic_to_remove.get("last_active_time", 0)) / 3600
            
            self.db.db.archived_topics.delete_one({"_id": topic_to_remove["_id"]})
            print(f"\033[1;31m[主题清理]\033[0m 已移除小主题: {topic_to_remove['name']} "
                  f"不活跃时间: {int(inactive_hours)}小时)")            
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 移除小主题失败: {str(e)}") 
