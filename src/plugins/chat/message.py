from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple, ForwardRef
import time
import jieba.analyse as jieba_analyse
import os
from datetime import datetime
from ...common.database import Database
from PIL import Image
from .config import BotConfig, global_config
import urllib3
from .cq_code import CQCode

Message = ForwardRef('Message')  # 添加这行

# 加载配置
bot_config = BotConfig.load_config()

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

#这个类是消息数据类，用于存储和管理消息数据。
#它定义了消息的属性，包括群组ID、用户ID、消息ID、原始消息内容、纯文本内容和时间戳。
#它还定义了两个辅助属性：keywords用于提取消息的关键词，is_plain_text用于判断消息是否为纯文本。


@dataclass
class Message:
    """消息数据类"""
    group_id: int = None
    user_id: int = None
    user_nickname: str = None  # 用户昵称
    group_name: str = None  # 群名称    
    
    message_id: int = None
    raw_message: str = None
    plain_text: str = None
    
    message_based_id: int = None
    reply_message: Dict = None  # 存储回复消息
    
    message_segments: List[Dict] = None  # 存储解析后的消息片段
    processed_plain_text: str = None  # 用于存储处理后的plain_text
    
    time: float = None
    
    is_emoji: bool = False # 是否是表情包

    
    
    reply_benefits: float = 0.0
    
    type: str = 'received' # 消息类型，可以是received或者send
    
    
    
    """消息数据类:思考消息"""
    
    # 思考状态相关属性
    is_thinking: bool = False
    thinking_text: str = "正在思考..."
    thingking_start_time: float = None
    thinking_time: float = 0
    
    received_message = ''
    thinking_response = ''
    
    def __post_init__(self):
        if self.time is None:
            self.time = int(time.time())
        
        if not self.user_nickname:
            self.user_nickname = self.get_user_nickname(self.user_id)
        
        if not self.group_name:
            self.group_name = self.get_groupname(self.group_id)
        
        if not self.processed_plain_text:
        # 解析消息片段
            if self.raw_message:
                # print(f"\033[1;34m[调试信息]\033[0m 原始消息: {self.raw_message}")
                self.message_segments = self.parse_message_segments(str(self.raw_message))
                self.processed_plain_text = ' '.join(
                    seg['translated_text']
                    for seg in self.message_segments
                )
                
        # print(f"\033[1;34m[调试]\033[0m pppttt消息: {self.processed_plain_text}")
    def get_user_nickname(self, user_id: int) -> str:
        """
        根据user_id获取用户昵称
        如果数据库中找不到，则返回默认昵称
        """
        if not user_id:
            return "未知用户"
        
        user_id = int(user_id)  
        if user_id == int(global_config.BOT_QQ):
            return "麦麦"
          
        # 使用数据库单例
        db = Database.get_instance()
        # 查找用户，打印查询条件和结果
        query = {'user_id': user_id}
        user = db.db.user_info.find_one(query)
        if user:
            return user.get('nickname') or f"用户{user_id}"
        else:
            return f"用户{user_id}"
        
    def get_groupname(self, group_id: int) -> str:
        if not group_id:
            return "未知群"
        group_id = int(group_id)    
        # 使用数据库单例
        db = Database.get_instance()
        # 查找用户，打印查询条件和结果
        query = {'group_id': group_id}
        group = db.db.group_info.find_one(query)
        if group:
            return group.get('group_name')
        else:
            return f"群{group_id}"
    
    def parse_message_segments(self, message: str) -> List[Dict]:
        """
        将消息解析为片段列表，包括纯文本和CQ码
        返回的列表中每个元素都是字典，包含：
        - type: 'text' 或 CQ码类型
        - data: 对于text类型是文本内容，对于CQ码是参数字典
        - translated_text: 经过处理（如AI翻译）后的文本
        """
        segments = []
        start = 0
        
        while True:
            # 查找下一个CQ码的开始位置
            cq_start = message.find('[CQ:', start)
            if cq_start == -1:
                # 如果没有找到更多CQ码，添加剩余文本
                if start < len(message):
                    text = message[start:].strip()
                    if text:  # 只添加非空文本
                        segments.append({
                            'type': 'text',
                            'data': {'text': text},
                            'translated_text': text
                        })
                break
                
            # 添加CQ码前的文本
            if cq_start > start:
                text = message[start:cq_start].strip()
                if text:  # 只添加非空文本
                    segments.append({
                        'type': 'text',
                        'data': {'text': text},
                        'translated_text': text
                    })
            
            # 查找CQ码的结束位置
            cq_end = message.find(']', cq_start)
            if cq_end == -1:
                # CQ码未闭合，作为普通文本处理
                text = message[cq_start:].strip()
                if text:
                    segments.append({
                        'type': 'text',
                        'data': {'text': text},
                        'translated_text': text
                    })
                break
                
            # 提取完整的CQ码并创建CQCode对象
            cq_code = message[cq_start:cq_end + 1]
            try:
                cq_obj = CQCode.from_cq_code(cq_code,reply = self.reply_message)
                # 设置必要的属性
                segments.append({
                    'type': cq_obj.type,
                    'data': cq_obj.params,
                    'translated_text': cq_obj.translated_plain_text
                })
            except Exception as e:
                import traceback
                print(f"\033[1;31m[错误]\033[0m 处理CQ码失败: {str(e)}")
                print(f"CQ码内容: {cq_code}")
                print(f"当前消息属性:")
                print(f"- group_id: {self.group_id}")
                print(f"- user_id: {self.user_id}")
                print(f"- user_nickname: {self.user_nickname}")
                print(f"- group_name: {self.group_name}")
                print("详细错误信息:")
                print(traceback.format_exc())
                # 处理失败时，将CQ码作为普通文本处理
                segments.append({
                    'type': 'text',
                    'data': {'text': cq_code},
                    'translated_text': cq_code
                })
            
            start = cq_end + 1
            
        # 检查是否只包含一个表情包CQ码
        if len(segments) == 1 and segments[0]['type'] == 'image':
            # 检查图片的 subtype 是否为 0（表情包）
            if segments[0]['data'].get('subtype') == '0':
                self.is_emoji = True
            
        return segments

class Message_Thinking:
    """消息思考类"""
    def __init__(self, message: Message,message_id: str):
        # 复制原始消息的基本属性
        self.group_id = message.group_id
        self.user_id = message.user_id
        self.user_nickname = message.user_nickname
        self.group_name = message.group_name
        
        self.message_id = message_id
        
        # 思考状态相关属性
        self.thinking_text = "正在思考..."
        self.time = int(time.time())
        
    def update_to_message(self, done_message: Message) -> Message:
        """更新为完整消息"""
        
        return done_message
    
    @property
    def processed_plain_text(self) -> str:
        """获取处理后的文本"""
        return self.thinking_text
    
    def __str__(self) -> str:
        return f"[思考中] 群:{self.group_id} 用户:{self.user_nickname} 时间:{self.time} 消息ID:{self.message_id}"
        
        
class MessageSet:
    """消息集合类，可以存储多个相关的消息"""
    def __init__(self, group_id: int, user_id: int, message_id: str):
        self.group_id = group_id
        self.user_id = user_id
        self.message_id = message_id
        self.messages: List[Message] = []
        self.time = round(time.time(), 2)
        
    def add_message(self, message: Message) -> None:
        """添加消息到集合"""
        self.messages.append(message)
        # 按时间排序
        self.messages.sort(key=lambda x: x.time)
        
    def get_message_by_index(self, index: int) -> Optional[Message]:
        """通过索引获取消息"""
        if 0 <= index < len(self.messages):
            return self.messages[index]
        return None
        
    def get_message_by_time(self, target_time: float) -> Optional[Message]:
        """获取最接近指定时间的消息"""
        if not self.messages:
            return None
            
        # 使用二分查找找到最接近的消息
        left, right = 0, len(self.messages) - 1
        while left < right:
            mid = (left + right) // 2
            if self.messages[mid].time < target_time:
                left = mid + 1
            else:
                right = mid
                
        return self.messages[left]
        
    def get_latest_message(self) -> Optional[Message]:
        """获取最新的消息"""
        return self.messages[-1] if self.messages else None
        
    def get_earliest_message(self) -> Optional[Message]:
        """获取最早的消息"""
        return self.messages[0] if self.messages else None
        
    def get_all_messages(self) -> List[Message]:
        """获取所有消息"""
        return self.messages.copy()
        
    def get_message_count(self) -> int:
        """获取消息数量"""
        return len(self.messages)
        
    def clear_messages(self) -> None:
        """清空所有消息"""
        self.messages.clear()
        
    def remove_message(self, message: Message) -> bool:
        """移除指定消息"""
        if message in self.messages:
            self.messages.remove(message)
            return True
        return False
        
    def __str__(self) -> str:
        return f"MessageSet(id={self.message_id}, count={len(self.messages)})"
        
    def __len__(self) -> int:
        return len(self.messages)
        
    @property
    def processed_plain_text(self) -> str:
        """获取所有消息的文本内容"""
        return "\n".join(msg.processed_plain_text for msg in self.messages if msg.processed_plain_text)
        
        
        
        
    
