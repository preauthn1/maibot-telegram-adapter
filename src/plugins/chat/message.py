import time
from dataclasses import dataclass
from typing import Dict, ForwardRef, List, Optional, Union

import urllib3
from loguru import logger

from .cq_code import CQCode, cq_code_tool
from .utils_cq import parse_cq_code
from .utils_user import get_groupname, get_user_cardname, get_user_nickname
from .utils_image import image_manager
from .message_base import Seg, GroupInfo, UserInfo, BaseMessageInfo, MessageBase
# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

#这个类是消息数据类，用于存储和管理消息数据。
#它定义了消息的属性，包括群组ID、用户ID、消息ID、原始消息内容、纯文本内容和时间戳。
#它还定义了两个辅助属性：keywords用于提取消息的关键词，is_plain_text用于判断消息是否为纯文本。
    
@dataclass
class MessageRecv(MessageBase):
    """接收消息类，用于处理从MessageCQ序列化的消息"""
    
    def __init__(self, message_dict: Dict):
        """从MessageCQ的字典初始化
        
        Args:
            message_dict: MessageCQ序列化后的字典
        """
        message_info = BaseMessageInfo(**message_dict.get('message_info', {}))
        message_segment = Seg(**message_dict.get('message_segment', {}))
        raw_message = message_dict.get('raw_message')
        
        super().__init__(
            message_info=message_info,
            message_segment=message_segment,
            raw_message=raw_message
        )
        
        # 处理消息内容
        self.processed_plain_text = ""  # 初始化为空字符串
        self.detailed_plain_text = ""   # 初始化为空字符串

    async def process(self) -> None:
        """处理消息内容，生成纯文本和详细文本
        
        这个方法必须在创建实例后显式调用，因为它包含异步操作。
        """
        self.processed_plain_text = await self._process_message_segments(self.message_segment)
        self.detailed_plain_text = self._generate_detailed_text()

    async def _process_message_segments(self, segment: Seg) -> str:
        """递归处理消息段，转换为文字描述
        
        Args:
            segment: 要处理的消息段
            
        Returns:
            str: 处理后的文本
        """
        if segment.type == 'seglist':
            # 处理消息段列表
            segments_text = []
            for seg in segment.data:
                processed = await self._process_message_segments(seg)
                if processed:
                    segments_text.append(processed)
            return ' '.join(segments_text)
        else:
            # 处理单个消息段
            return await self._process_single_segment(segment)

    async def _process_single_segment(self, seg: Seg) -> str:
        """处理单个消息段
        
        Args:
            seg: 要处理的消息段
            
        Returns:
            str: 处理后的文本
        """
        try:
            if seg.type == 'text':
                return seg.data
            elif seg.type == 'image':
                # 如果是base64图片数据
                if isinstance(seg.data, str) and seg.data.startswith(('data:', 'base64:')):
                    return await image_manager.get_image_description(seg.data)
                return '[图片]'
            elif seg.type == 'emoji':
                if isinstance(seg.data, str) and seg.data.startswith(('data:', 'base64:')):
                    return await image_manager.get_emoji_description(seg.data)
                return '[表情]'
            else:
                return f"[{seg.type}:{str(seg.data)}]"
        except Exception as e:
            logger.error(f"处理消息段失败: {str(e)}, 类型: {seg.type}, 数据: {seg.data}")
            return f"[处理失败的{seg.type}消息]"

    def _generate_detailed_text(self) -> str:
        """生成详细文本，包含时间和用户信息"""
        time_str = time.strftime("%m-%d %H:%M:%S", time.localtime(self.message_info.time))
        user_info = self.message_info.user_info
        name = (
            f"{user_info.user_nickname}(ta的昵称:{user_info.user_cardname},ta的id:{user_info.user_id})"
            if user_info.user_cardname!=''
            else f"{user_info.user_nickname}(ta的id:{user_info.user_id})"
        )
        return f"[{time_str}] {name}: {self.processed_plain_text}\n"

@dataclass
class MessageProcessBase(MessageBase):
    """消息处理基类，用于处理中和发送中的消息"""
    
    def __init__(
        self,
        message_id: str,
        user_id: int,
        group_id: Optional[int] = None,
        platform: str = "qq",
        message_segment: Optional[Seg] = None,
        reply: Optional['MessageRecv'] = None
    ):
        # 构造用户信息
        user_info = UserInfo(
            platform=platform,
            user_id=user_id,
            user_nickname=get_user_nickname(user_id),
            user_cardname=get_user_cardname(user_id) if group_id else None
        )

        # 构造群组信息（如果有）
        group_info = None
        if group_id:
            group_info = GroupInfo(
                platform=platform,
                group_id=group_id,
                group_name=get_groupname(group_id)
            )

        # 构造基础消息信息
        message_info = BaseMessageInfo(
            platform=platform,
            message_id=message_id,
            time=int(time.time()),
            group_info=group_info,
            user_info=user_info
        )

        # 调用父类初始化
        super().__init__(
            message_info=message_info,
            message_segment=message_segment,
            raw_message=None
        )

        # 处理状态相关属性
        self.thinking_start_time = int(time.time())
        self.thinking_time = 0
        
        # 文本处理相关属性
        self.processed_plain_text = ""
        self.detailed_plain_text = ""
        
        # 回复消息
        self.reply = reply

    def update_thinking_time(self) -> float:
        """更新思考时间"""
        self.thinking_time = round(time.time() - self.thinking_start_time, 2)
        return self.thinking_time

    async def _process_message_segments(self, segment: Seg) -> str:
        """递归处理消息段，转换为文字描述
        
        Args:
            segment: 要处理的消息段
            
        Returns:
            str: 处理后的文本
        """
        if segment.type == 'seglist':
            # 处理消息段列表
            segments_text = []
            for seg in segment.data:
                processed = await self._process_message_segments(seg)
                if processed:
                    segments_text.append(processed)
            return ' '.join(segments_text)
        else:
            # 处理单个消息段
            return await self._process_single_segment(segment)

    async def _process_single_segment(self, seg: Seg) -> str:
        """处理单个消息段
        
        Args:
            seg: 要处理的消息段
            
        Returns:
            str: 处理后的文本
        """
        try:
            if seg.type == 'text':
                return seg.data
            elif seg.type == 'image':
                # 如果是base64图片数据
                if isinstance(seg.data, str) and seg.data.startswith(('data:', 'base64:')):
                    return await image_manager.get_image_description(seg.data)
                return '[图片]'
            elif seg.type == 'emoji':
                if isinstance(seg.data, str) and seg.data.startswith(('data:', 'base64:')):
                    return await image_manager.get_emoji_description(seg.data)
                return '[表情]'
            elif seg.type == 'at':
                return f"[@{seg.data}]"
            elif seg.type == 'reply':
                if self.reply and hasattr(self.reply, 'processed_plain_text'):
                    return f"[回复：{self.reply.processed_plain_text}]"
            else:
                return f"[{seg.type}:{str(seg.data)}]"
        except Exception as e:
            logger.error(f"处理消息段失败: {str(e)}, 类型: {seg.type}, 数据: {seg.data}")
            return f"[处理失败的{seg.type}消息]"

    def _generate_detailed_text(self) -> str:
        """生成详细文本，包含时间和用户信息"""
        time_str = time.strftime("%m-%d %H:%M:%S", time.localtime(self.message_info.time))
        user_info = self.message_info.user_info
        name = (
            f"{user_info.user_nickname}(ta的昵称:{user_info.user_cardname},ta的id:{user_info.user_id})"
            if user_info.user_cardname != ''
            else f"{user_info.user_nickname}(ta的id:{user_info.user_id})"
        )
        return f"[{time_str}] {name}: {self.processed_plain_text}\n"

@dataclass
class MessageThinking(MessageProcessBase):
    """思考状态的消息类"""
    
    def __init__(
        self,
        message_id: str,
        user_id: int,
        group_id: Optional[int] = None,
        platform: str = "qq",
        reply: Optional['MessageRecv'] = None
    ):
        # 调用父类初始化
        super().__init__(
            message_id=message_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
            message_segment=None,  # 思考状态不需要消息段
            reply=reply
        )
        
        # 思考状态特有属性
        self.interrupt = False

@dataclass
class MessageSending(MessageProcessBase):
    """发送状态的消息类"""
    
    def __init__(
        self,
        message_id: str,
        user_id: int,
        message_segment: Seg,
        group_id: Optional[int] = None,
        reply: Optional['MessageRecv'] = None,
        platform: str = "qq",
        is_head: bool = False
    ):
        # 调用父类初始化
        super().__init__(
            message_id=message_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
            message_segment=message_segment,
            reply=reply
        )
        
        # 发送状态特有属性
        self.reply_to_message_id = reply.message_info.message_id if reply else None
        self.is_head = is_head

    async def process(self) -> None:
        """处理消息内容，生成纯文本和详细文本"""
        if self.message_segment:
            self.processed_plain_text = await self._process_message_segments(self.message_segment)
            self.detailed_plain_text = self._generate_detailed_text()

    @classmethod
    def from_thinking(
        cls,
        thinking: MessageThinking,
        message_segment: Seg,
        reply: Optional['MessageRecv'] = None,
        is_head: bool = False
    ) -> 'MessageSending':
        """从思考状态消息创建发送状态消息"""
        return cls(
            message_id=thinking.message_info.message_id,
            user_id=thinking.message_info.user_info.user_id,
            message_segment=message_segment,
            group_id=thinking.message_info.group_info.group_id if thinking.message_info.group_info else None,
            reply=reply or thinking.reply,
            platform=thinking.message_info.platform,
            is_head=is_head
        )

@dataclass
class MessageSet:
    """消息集合类，可以存储多个发送消息"""
    def __init__(self, group_id: int, user_id: int, message_id: str):
        self.group_id = group_id
        self.user_id = user_id
        self.message_id = message_id
        self.messages: List[MessageSending] = []
        self.time = round(time.time(), 2)
        
    def add_message(self, message: MessageSending) -> None:
        """添加消息到集合"""
        if not isinstance(message, MessageSending):
            raise TypeError("MessageSet只能添加MessageSending类型的消息")
        self.messages.append(message)
        self.messages.sort(key=lambda x: x.message_info.time)
        
    def get_message_by_index(self, index: int) -> Optional[MessageSending]:
        """通过索引获取消息"""
        if 0 <= index < len(self.messages):
            return self.messages[index]
        return None
        
    def get_message_by_time(self, target_time: float) -> Optional[MessageSending]:
        """获取最接近指定时间的消息"""
        if not self.messages:
            return None
            
        left, right = 0, len(self.messages) - 1
        while left < right:
            mid = (left + right) // 2
            if self.messages[mid].message_info.time < target_time:
                left = mid + 1
            else:
                right = mid
                
        return self.messages[left]
        
    def clear_messages(self) -> None:
        """清空所有消息"""
        self.messages.clear()
        
    def remove_message(self, message: MessageSending) -> bool:
        """移除指定消息"""
        if message in self.messages:
            self.messages.remove(message)
            return True
        return False
        
    def __str__(self) -> str:
        return f"MessageSet(id={self.message_id}, count={len(self.messages)})"
        
    def __len__(self) -> int:
        return len(self.messages)
        

    
