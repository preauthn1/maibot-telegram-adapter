import time
from ...common.database import Database
from nonebot.adapters.onebot.v11 import Bot
from typing import Optional, Tuple
import asyncio

class Impression:
    traits: str = None
    called: str = None
    know_time: float = None
    
    relationship_value: float = None

class Relationship:
    user_id: int = None
    # impression: Impression = None
    # group_id: int = None
    # group_name: str = None
    gender: str = None
    age: int = None
    nickname: str = None
    relationship_value: float = None
    saved = False
    
    def __init__(self, user_id: int, data=None, **kwargs):
        if isinstance(data, dict):
            # 如果输入是字典，使用字典解析
            self.user_id = data.get('user_id')
            self.gender = data.get('gender')
            self.age = data.get('age')
            self.nickname = data.get('nickname')
            self.relationship_value = data.get('relationship_value', 0.0)
            self.saved = data.get('saved', False)
        else:
            # 如果是直接传入属性值
            self.user_id = kwargs.get('user_id')
            self.gender = kwargs.get('gender')
            self.age = kwargs.get('age')
            self.nickname = kwargs.get('nickname')
            self.relationship_value = kwargs.get('relationship_value', 0.0)
            self.saved = kwargs.get('saved', False)
    

        

class RelationshipManager:
    def __init__(self):
        self.relationships: dict[int, Relationship] = {}  # user_id -> Relationship
        #保存 qq号，现在使用昵称，别称
        self.id_name_nickname_table: dict[str, str, list] = {}  # name -> [nickname, nickname, ...]
    
    async def update_relationship(self, user_id: int, data=None, **kwargs):
        # 检查是否在内存中已存在
        relationship = self.relationships.get(user_id)
        if relationship:
            # 如果存在，更新现有对象
            if isinstance(data, dict):
                for key, value in data.items():
                    if hasattr(relationship, key) and value is not None:
                        setattr(relationship, key, value)
            else:
                for key, value in kwargs.items():
                    if hasattr(relationship, key) and value is not None:
                        setattr(relationship, key, value)
        else:
            # 如果不存在，创建新对象
            relationship = Relationship(user_id, data=data) if isinstance(data, dict) else Relationship(user_id, **kwargs)
            self.relationships[user_id] = relationship

        # 保存到数据库
        await self.storage_relationship(relationship)
        relationship.saved = True
        
        return relationship
    
    async def update_relationship_value(self, user_id: int, **kwargs):
        # 检查是否在内存中已存在
        relationship = self.relationships.get(user_id)
        if relationship:
            for key, value in kwargs.items():
                if key == 'relationship_value':
                    relationship.relationship_value += value
            await self.storage_relationship(relationship)
            relationship.saved = True
            return relationship
        else:
            print(f"\033[1;31m[关系管理]\033[0m 用户 {user_id} 不存在，无法更新")
            return None
    
    
    def get_relationship(self, user_id: int) -> Optional[Relationship]:
        """获取用户关系对象"""
        if user_id in self.relationships:
            return self.relationships[user_id]
        else:
            return 0
    
    async def load_relationship(self, data: dict) -> Relationship:
        """从数据库加载或创建新的关系对象"""       
        rela = Relationship(user_id=data['user_id'], data=data)
        rela.saved = True
        return rela
    
    async def _start_relationship_manager(self):
        """每5分钟自动保存一次关系数据"""
        db = Database.get_instance()
        # 获取所有关系记录
        all_relationships = db.db.relationships.find({})
        # 依次加载每条记录
        for data in all_relationships:
            user_id = data['user_id']
            relationship = await self.load_relationship(data)
            self.relationships[user_id] = relationship  
        print(f"\033[1;32m[关系管理]\033[0m 已加载 {len(self.relationships)} 条关系记录")
        
        while True:
            print(f"\033[1;32m[关系管理]\033[0m 正在自动保存关系")
            await asyncio.sleep(300)  # 等待300秒(5分钟)
            await self._save_all_relationships()
    
    async def _save_all_relationships(self):
        """将所有关系数据保存到数据库"""         
        # 保存所有关系数据
        for userid, relationship in self.relationships:
            if not relationship.saved:
                relationship.saved = True
                await self.storage_relationship(relationship)
    
    async def storage_relationship(self,relationship: Relationship):
        """
        将关系记录存储到数据库中
        """
        user_id = relationship.user_id
        nickname = relationship.nickname
        relationship_value = relationship.relationship_value
        gender = relationship.gender
        age = relationship.age
        saved = relationship.saved
        
        db = Database.get_instance()
        db.db.relationships.update_one(
            {'user_id': user_id},
            {'$set': {
                'nickname': nickname,
                'relationship_value': relationship_value,
                'gender': gender,
                'age': age,
                'saved': saved
            }},
            upsert=True
        )

    @staticmethod
    async def get_user_nickname(bot: Bot, user_id: int, group_id: int = None) -> Tuple[str, Optional[str]]:
        """
        通过QQ API获取用户昵称
        """

        # 获取QQ昵称
        stranger_info = await bot.get_stranger_info(user_id=user_id)
        qq_nickname = stranger_info['nickname']
        
        # 如果提供了群号，获取群昵称
        if group_id:
            try:
                member_info = await bot.get_group_member_info(
                    group_id=group_id,
                    user_id=user_id,
                    no_cache=True
                )
                group_nickname = member_info['card'] or None
                return qq_nickname, group_nickname
            except:
                return qq_nickname, None
        
        return qq_nickname, None

    def print_all_relationships(self):
        """打印内存中所有的关系记录"""
        print("\n\033[1;32m[关系管理]\033[0m 当前内存中的所有关系:")
        print("=" * 50)
        
        if not self.relationships:
            print("暂无关系记录")
            return
            
        for user_id, relationship in self.relationships.items():
            print(f"用户ID: {user_id}")
            print(f"昵称: {relationship.nickname}")
            print(f"好感度: {relationship.relationship_value}")
            print("-" * 30)
            
        print("=" * 50)




        
        
relationship_manager = RelationshipManager()