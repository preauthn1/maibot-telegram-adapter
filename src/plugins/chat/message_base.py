from dataclasses import dataclass, asdict
from typing import List, Optional, Union, Any, Dict

@dataclass
class Seg(dict):
    """消息片段类，用于表示消息的不同部分
    
    Attributes:
        type: 片段类型，可以是 'text'、'image'、'seglist' 等
        data: 片段的具体内容
            - 对于 text 类型，data 是字符串
            - 对于 image 类型，data 是 base64 字符串
            - 对于 seglist 类型，data 是 Seg 列表
        translated_data: 经过翻译处理的数据（可选）
    """
    type: str
    data: Union[str, List['Seg']]
    translated_data: Optional[str] = None

    def __init__(self, type: str, data: Union[str, List['Seg']], translated_data: Optional[str] = None):
        """初始化实例，确保字典和属性同步"""
        # 先初始化字典
        super().__init__(type=type, data=data)
        if translated_data is not None:
            self['translated_data'] = translated_data
            
        # 再初始化属性
        object.__setattr__(self, 'type', type)
        object.__setattr__(self, 'data', data)
        object.__setattr__(self, 'translated_data', translated_data)
        
        # 验证数据类型
        self._validate_data()

    def _validate_data(self) -> None:
        """验证数据类型的正确性"""
        if self.type == 'seglist' and not isinstance(self.data, list):
            raise ValueError("seglist类型的data必须是列表")
        elif self.type == 'text' and not isinstance(self.data, str):
            raise ValueError("text类型的data必须是字符串")
        elif self.type == 'image' and not isinstance(self.data, str):
            raise ValueError("image类型的data必须是字符串")

    def __setattr__(self, name: str, value: Any) -> None:
        """重写属性设置，同时更新字典值"""
        # 更新属性
        object.__setattr__(self, name, value)
        # 同步更新字典
        if name in ['type', 'data', 'translated_data']:
            self[name] = value

    def __setitem__(self, key: str, value: Any) -> None:
        """重写字典值设置，同时更新属性"""
        # 更新字典
        super().__setitem__(key, value)
        # 同步更新属性
        if key in ['type', 'data', 'translated_data']:
            object.__setattr__(self, key, value)

    def to_dict(self) -> Dict:
        """转换为字典格式"""
        result = {'type': self.type}
        if self.type == 'seglist':
            result['data'] = [seg.to_dict() for seg in self.data]
        else:
            result['data'] = self.data
        if self.translated_data is not None:
            result['translated_data'] = self.translated_data
        return result

@dataclass
class GroupInfo:
    """群组信息类"""
    platform: Optional[str] = None
    group_id: Optional[int] = None
    group_name: Optional[str] = None  # 群名称

    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return {k: v for k, v in asdict(self).items() if v is not None}

@dataclass
class UserInfo:
    """用户信息类"""
    platform: Optional[str] = None
    user_id: Optional[int] = None
    user_nickname: Optional[str] = None  # 用户昵称
    user_cardname: Optional[str] = None  # 用户群昵称

    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return {k: v for k, v in asdict(self).items() if v is not None}

@dataclass
class BaseMessageInfo:
    """消息信息类"""
    platform: Optional[str] = None
    message_id: Optional[int,str] = None
    time: Optional[int] = None
    group_info: Optional[GroupInfo] = None
    user_info: Optional[UserInfo] = None

    def to_dict(self) -> Dict:
        """转换为字典格式"""
        result = {}
        for field, value in asdict(self).items():
            if value is not None:
                if isinstance(value, (GroupInfo, UserInfo)):
                    result[field] = value.to_dict()
                else:
                    result[field] = value
        return result

@dataclass
class MessageBase:
    """消息类"""
    message_info: BaseMessageInfo
    message_segment: Seg
    raw_message: Optional[str] = None  # 原始消息，包含未解析的cq码

    def to_dict(self) -> Dict:
        """转换为字典格式
        
        Returns:
            Dict: 包含所有非None字段的字典，其中：
                - message_info: 转换为字典格式
                - message_segment: 转换为字典格式
                - raw_message: 如果存在则包含
        """
        result = {
            'message_info': self.message_info.to_dict(),
            'message_segment': self.message_segment.to_dict()
        }
        if self.raw_message is not None:
            result['raw_message'] = self.raw_message
        return result

    @classmethod
    def from_dict(cls, data: Dict) -> 'MessageBase':
        """从字典创建MessageBase实例
        
        Args:
            data: 包含必要字段的字典
            
        Returns:
            MessageBase: 新的实例
        """
        message_info = BaseMessageInfo(**data.get('message_info', {}))
        message_segment = Seg(**data.get('message_segment', {}))
        raw_message = data.get('raw_message')
        return cls(
            message_info=message_info,
            message_segment=message_segment,
            raw_message=raw_message
        )

    
    
