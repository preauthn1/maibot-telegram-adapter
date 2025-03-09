import asyncio
from typing import Optional, Union

from ...common.database import Database
from .message_base import UserInfo


class Impression:
    traits: str = None
    called: str = None
    know_time: float = None
    
    relationship_value: float = None

class Relationship:
    user_id: int = None
    platform: str = None
    gender: str = None
    age: int = None
    nickname: str = None
    relationship_value: float = None
    saved = False
    
    def __init__(self, user_id: int = None, data: dict = None, user_info: UserInfo = None, **kwargs):
        if isinstance(data, dict):
            # 如果输入是字典，使用字典解析
            self.user_id = data.get('user_id')
            self.platform = data.get('platform', 'qq')
            self.gender = data.get('gender')
            self.age = data.get('age')
            self.nickname = data.get('nickname')
            self.relationship_value = data.get('relationship_value', 0.0)
            self.saved = data.get('saved', False)
        elif user_info is not None:
            # 如果输入是UserInfo对象
            self.user_id = user_info.user_id
            self.platform = user_info.platform or 'qq'
            self.nickname = user_info.user_nickname or user_info.user_cardname or "某人"
            self.relationship_value = kwargs.get('relationship_value', 0.0)
            self.gender = kwargs.get('gender')
            self.age = kwargs.get('age')
            self.saved = kwargs.get('saved', False)
        else:
            # 如果是直接传入属性值
            self.user_id = kwargs.get('user_id')
            self.platform = kwargs.get('platform', 'qq')
            self.gender = kwargs.get('gender')
            self.age = kwargs.get('age')
            self.nickname = kwargs.get('nickname')
            self.relationship_value = kwargs.get('relationship_value', 0.0)
            self.saved = kwargs.get('saved', False)
    

class RelationshipManager:
    def __init__(self):
        self.relationships: dict[tuple[int, str], Relationship] = {}  # 修改为使用(user_id, platform)作为键
    
    async def update_relationship(self, 
                                user_id: int = None, 
                                platform: str = None, 
                                user_info: UserInfo = None,
                                data: dict = None, 
                                **kwargs) -> Optional[Relationship]:
        """更新或创建关系
        Args:
            user_id: 用户ID（可选，如果提供user_info则不需要）
            platform: 平台（可选，如果提供user_info则不需要）
            user_info: 用户信息对象（可选）
            data: 字典格式的数据（可选）
            **kwargs: 其他参数
        Returns:
            Relationship: 关系对象
        """
        # 确定user_id和platform
        if user_info is not None:
            user_id = user_info.user_id
            platform = user_info.platform or 'qq'
        else:
            platform = platform or 'qq'
            
        if user_id is None:
            raise ValueError("必须提供user_id或user_info")
            
        # 使用(user_id, platform)作为键
        key = (user_id, platform)
        
        # 检查是否在内存中已存在
        relationship = self.relationships.get(key)
        if relationship:
            # 如果存在，更新现有对象
            if isinstance(data, dict):
                for k, value in data.items():
                    if hasattr(relationship, k) and value is not None:
                        setattr(relationship, k, value)
            else:
                for k, value in kwargs.items():
                    if hasattr(relationship, k) and value is not None:
                        setattr(relationship, k, value)
        else:
            # 如果不存在，创建新对象
            if user_info is not None:
                relationship = Relationship(user_info=user_info, **kwargs)
            elif isinstance(data, dict):
                data['platform'] = platform
                relationship = Relationship(user_id=user_id, data=data)
            else:
                kwargs['platform'] = platform
                kwargs['user_id'] = user_id
                relationship = Relationship(**kwargs)
            self.relationships[key] = relationship

        # 保存到数据库
        await self.storage_relationship(relationship)
        relationship.saved = True
        
        return relationship
    
    async def update_relationship_value(self, 
                                      user_id: int = None, 
                                      platform: str = None,
                                      user_info: UserInfo = None,
                                      **kwargs) -> Optional[Relationship]:
        """更新关系值
        Args:
            user_id: 用户ID（可选，如果提供user_info则不需要）
            platform: 平台（可选，如果提供user_info则不需要）
            user_info: 用户信息对象（可选）
            **kwargs: 其他参数
        Returns:
            Relationship: 关系对象
        """
        # 确定user_id和platform
        if user_info is not None:
            user_id = user_info.user_id
            platform = user_info.platform or 'qq'
        else:
            platform = platform or 'qq'
            
        if user_id is None:
            raise ValueError("必须提供user_id或user_info")
            
        # 使用(user_id, platform)作为键
        key = (user_id, platform)
        
        # 检查是否在内存中已存在
        relationship = self.relationships.get(key)
        if relationship:
            for k, value in kwargs.items():
                if k == 'relationship_value':
                    relationship.relationship_value += value
            await self.storage_relationship(relationship)
            relationship.saved = True
            return relationship
        else:
            # 如果不存在且提供了user_info，则创建新的关系
            if user_info is not None:
                return await self.update_relationship(user_info=user_info, **kwargs)
            print(f"\033[1;31m[关系管理]\033[0m 用户 {user_id}({platform}) 不存在，无法更新")
            return None
    
    def get_relationship(self, 
                        user_id: int = None, 
                        platform: str = None,
                        user_info: UserInfo = None) -> Optional[Relationship]:
        """获取用户关系对象
        Args:
            user_id: 用户ID（可选，如果提供user_info则不需要）
            platform: 平台（可选，如果提供user_info则不需要）
            user_info: 用户信息对象（可选）
        Returns:
            Relationship: 关系对象
        """
        # 确定user_id和platform
        if user_info is not None:
            user_id = user_info.user_id
            platform = user_info.platform or 'qq'
        else:
            platform = platform or 'qq'
            
        if user_id is None:
            raise ValueError("必须提供user_id或user_info")
            
        key = (user_id, platform)
        if key in self.relationships:
            return self.relationships[key]
        else:
            return 0
    
    async def load_relationship(self, data: dict) -> Relationship:
        """从数据库加载或创建新的关系对象"""
        # 确保data中有platform字段，如果没有则默认为'qq'
        if 'platform' not in data:
            data['platform'] = 'qq'
            
        rela = Relationship(data=data)
        rela.saved = True
        key = (rela.user_id, rela.platform)
        self.relationships[key] = rela
        return rela
    
    async def load_all_relationships(self):
        """加载所有关系对象"""
        db = Database.get_instance()
        all_relationships = db.db.relationships.find({})
        for data in all_relationships:
            await self.load_relationship(data)
    
    async def _start_relationship_manager(self):
        """每5分钟自动保存一次关系数据"""
        db = Database.get_instance()
        # 获取所有关系记录
        all_relationships = db.db.relationships.find({})
        # 依次加载每条记录
        for data in all_relationships:
            await self.load_relationship(data)
        print(f"\033[1;32m[关系管理]\033[0m 已加载 {len(self.relationships)} 条关系记录")
        
        while True:
            print("\033[1;32m[关系管理]\033[0m 正在自动保存关系")
            await asyncio.sleep(300)  # 等待300秒(5分钟)
            await self._save_all_relationships()
    
    async def _save_all_relationships(self):
        """将所有关系数据保存到数据库"""         
        # 保存所有关系数据
        for (userid, platform), relationship in self.relationships.items():
            if not relationship.saved:
                relationship.saved = True
                await self.storage_relationship(relationship)
    
    async def storage_relationship(self, relationship: Relationship):
        """将关系记录存储到数据库中"""
        user_id = relationship.user_id
        platform = relationship.platform
        nickname = relationship.nickname
        relationship_value = relationship.relationship_value
        gender = relationship.gender
        age = relationship.age
        saved = relationship.saved
        
        db = Database.get_instance()
        db.db.relationships.update_one(
            {'user_id': user_id, 'platform': platform},
            {'$set': {
                'platform': platform,
                'nickname': nickname,
                'relationship_value': relationship_value,
                'gender': gender,
                'age': age,
                'saved': saved
            }},
            upsert=True
        )
        
    def get_name(self, 
                 user_id: int = None, 
                 platform: str = None,
                 user_info: UserInfo = None) -> str:
        """获取用户昵称
        Args:
            user_id: 用户ID（可选，如果提供user_info则不需要）
            platform: 平台（可选，如果提供user_info则不需要）
            user_info: 用户信息对象（可选）
        Returns:
            str: 用户昵称
        """
        # 确定user_id和platform
        if user_info is not None:
            user_id = user_info.user_id
            platform = user_info.platform or 'qq'
        else:
            platform = platform or 'qq'
            
        if user_id is None:
            raise ValueError("必须提供user_id或user_info")
            
        # 确保user_id是整数类型
        user_id = int(user_id)
        key = (user_id, platform)
        if key in self.relationships:
            return self.relationships[key].nickname
        elif user_info is not None:
            return user_info.user_nickname or user_info.user_cardname or "某人"
        else:
            return "某人"


relationship_manager = RelationshipManager()