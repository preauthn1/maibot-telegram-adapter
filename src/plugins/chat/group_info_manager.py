from typing import Dict, Optional
from ...common.database import Database
import time

class GroupInfoManager:
    def __init__(self):
        self.db = Database.get_instance()
        # 确保必要的集合存在
        self._ensure_collections()
        
    def _ensure_collections(self):
        """确保数据库中有必要的集合"""
        collections = self.db.db.list_collection_names()
        if 'group_info' not in collections:
            self.db.db.create_collection('group_info')
        if 'user_info' not in collections:
            self.db.db.create_collection('user_info')
            
    async def update_group_info(self, group_id: int, group_name: str, group_notice: str = "", 
                              member_count: int = 0, admins: list = None):
        """更新群组信息"""
        try:
            group_data = {
                "group_id": group_id,
                "group_name": group_name,
                "group_notice": group_notice,
                "member_count": member_count,
                "admins": admins or [],
                "last_updated": time.time()
            }
            
            # 使用 upsert 来更新或插入数据
            self.db.db.group_info.update_one(
                {"group_id": group_id},
                {"$set": group_data},
                upsert=True
            )
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 更新群信息失败: {str(e)}")
            
    async def update_user_info(self, user_id: int, nickname: str, group_id: int = None, 
                             group_card: str = None, age: int = None, gender: str = None, 
                             location: str = None):
        """更新用户信息"""
        try:
            # 基础用户数据
            user_data = {
                "user_id": user_id,
                "nickname": nickname,
                "last_updated": time.time()
            }
            
            # 添加可选字段
            if age is not None:
                user_data["age"] = age
            if gender is not None:
                user_data["gender"] = gender
            if location is not None:
                user_data["location"] = location
                
            # 如果提供了群相关信息，更新用户在该群的信息
            if group_id is not None:
                group_info_key = f"group_info.{group_id}"
                group_data = {
                    group_info_key: {
                        "group_card": group_card,
                        "last_active": time.time()
                    }
                }
                user_data.update(group_data)
            
            # 使用 upsert 来更新或插入数据
            result = self.db.db.user_info.update_one(
                {"user_id": user_id},
                {
                    "$set": user_data,
                    "$addToSet": {"groups": group_id} if group_id else {}
                },
                upsert=True
            )
            
            # print(f"\033[1;32m[用户信息]\033[0m 更新用户 {nickname}({user_id}) 的信息 {'成功' if result.modified_count > 0 or result.upserted_id else '未变化'}")
            
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 更新用户信息失败: {str(e)}")
            print(f"用户ID: {user_id}, 昵称: {nickname}, 群ID: {group_id}, 群名片: {group_card}")
            
    async def get_group_info(self, group_id: int) -> Optional[Dict]:
        """获取群组信息"""
        try:
            return self.db.db.group_info.find_one({"group_id": group_id})
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 获取群信息失败: {str(e)}")
            return None
            
    async def get_user_info(self, user_id: int, group_id: int = None) -> Optional[Dict]:
        """获取用户信息"""
        try:
            user_info = self.db.db.user_info.find_one({"user_id": user_id})
            if user_info and group_id:
                # 添加该用户在特定群的信息
                group_info_key = f"group_info.{group_id}"
                user_info["current_group_info"] = user_info.get(group_info_key, {})
            return user_info
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 获取用户信息失败: {str(e)}")
            return None 