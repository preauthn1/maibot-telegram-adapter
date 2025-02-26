from typing import List, Dict, Optional
import random
from ...common.database import Database
import os
import json
from dataclasses import dataclass
import jieba.analyse as jieba_analyse
import aiohttp
import hashlib
from datetime import datetime
import base64
import shutil
from .config import global_config, llm_config
import asyncio
import time


class EmojiManager:
    _instance = None
    EMOJI_DIR = "data/emoji"  # 表情包存储目录
    
    EMOTION_KEYWORDS = {
        'happy': ['开心', '快乐', '高兴', '欢喜', '笑', '喜悦', '兴奋', '愉快', '乐', '好'],
        'angry': ['生气', '愤怒', '恼火', '不爽', '火大', '怒', '气愤', '恼怒', '发火', '不满'],
        'sad': ['伤心', '难过', '悲伤', '痛苦', '哭', '忧伤', '悲痛', '哀伤', '委屈', '失落'],
        'surprised': ['惊讶', '震惊', '吃惊', '意外', '惊', '诧异', '惊奇', '惊喜', '不敢相信', '目瞪口呆'],
        'disgusted': ['恶心', '讨厌', '厌恶', '反感', '嫌弃', '恶', '嫌恶', '憎恶', '不喜欢', '烦'],
        'fearful': ['害怕', '恐惧', '惊恐', '担心', '怕', '惊吓', '惊慌', '畏惧', '胆怯', '惧'],
        'neutral': ['普通', '一般', '还行', '正常', '平静', '平淡', '一般般', '凑合', '还好', '就这样']
    }
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.db = None
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        self.db = Database.get_instance()
        self._scan_task = None
        
    def _ensure_emoji_dir(self):
        """确保表情存储目录存在"""
        os.makedirs(self.EMOJI_DIR, exist_ok=True)
    
    def initialize(self):
        """初始化数据库连接和表情目录"""
        if not self._initialized:
            try:
                self.db = Database.get_instance()
                self._ensure_emoji_collection()
                self._ensure_emoji_dir()
                self._initialized = True
                # 启动时执行一次完整性检查
                self.check_emoji_file_integrity()
            except Exception as e:
                print(f"\033[1;31m[错误]\033[0m 初始化表情管理器失败: {str(e)}")
                
    def _ensure_db(self):
        """确保数据库已初始化"""
        if not self._initialized:
            self.initialize()
        if not self._initialized:
            raise RuntimeError("EmojiManager not initialized")
        
    def _ensure_emoji_collection(self):
        """确保emoji集合存在并创建索引"""
        if 'emoji' not in self.db.db.list_collection_names():
            self.db.db.create_collection('emoji')
            self.db.db.emoji.create_index([('tags', 1)])
            self.db.db.emoji.create_index([('filename', 1)], unique=True)
            
    def record_usage(self, emoji_id: str):
        """记录表情使用次数"""
        try:
            self._ensure_db()
            self.db.db.emoji.update_one(
                {'_id': emoji_id},
                {'$inc': {'usage_count': 1}}
            )
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 记录表情使用失败: {str(e)}")
            
    async def _get_emotion_from_text(self, text: str) -> List[str]:
        """从文本中识别情感关键词，使用DeepSeek API进行分析
        Args:
            text: 输入文本
        Returns:
            List[str]: 匹配到的情感标签列表
        """
        try:
            # 准备请求数据
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {llm_config.SILICONFLOW_API_KEY}"
            }
            
            payload = {
                "model": "deepseek-ai/DeepSeek-V3",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f'分析这段文本："{text}"，从"happy,angry,sad,surprised,disgusted,fearful,neutral"中选出最匹配的1个情感标签。只需要返回标签，不要输出其他任何内容。'
                            }
                        ]
                    }
                ],
                "max_tokens": 50,
                "temperature": 0.3
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{llm_config.SILICONFLOW_BASE_URL}chat/completions",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status != 200:
                        print(f"\033[1;31m[错误]\033[0m API请求失败: {await response.text()}")
                        return ['neutral']
                    
                    result = json.loads(await response.text())
                    if "choices" in result and len(result["choices"]) > 0:
                        emotion = result["choices"][0]["message"]["content"].strip().lower()
                        # 确保返回的标签是有效的
                        if emotion in self.EMOTION_KEYWORDS:
                            print(f"\033[1;32m[成功]\033[0m 识别到的情感: {emotion}")
                            return [emotion]  # 返回单个情感标签的列表
            
            return ['neutral']  # 如果无法识别情感，返回neutral
            
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 情感分析失败: {str(e)}")
            return ['neutral']

    async def get_emoji_for_emotion(self, emotion_tag: str) -> Optional[str]:
        try:
            self._ensure_db()
                
            # 构建查询条件：标签匹配任一情感
            query = {'tags': {'$in': emotion_tag}}
            
            # print(f"\033[1;34m[调试]\033[0m 表情查询条件: {query}")
            
            try:
                # 随机获取一个匹配的表情
                emoji = self.db.db.emoji.aggregate([
                    {'$match': query},
                    {'$sample': {'size': 1}}
                ]).next()
                print(f"\033[1;32m[成功]\033[0m 找到匹配的表情")
                if emoji and 'path' in emoji:
                    # 更新使用次数
                    self.db.db.emoji.update_one(
                        {'_id': emoji['_id']},
                        {'$inc': {'usage_count': 1}}
                    )
                    return emoji['path']
            except StopIteration:
                # 如果没有匹配的表情，从所有表情中随机选择一个
                print(f"\033[1;33m[提示]\033[0m 未找到匹配的表情，随机选择一个")
                try:
                    emoji = self.db.db.emoji.aggregate([
                        {'$sample': {'size': 1}}
                    ]).next()
                    if emoji and 'path' in emoji:
                        # 更新使用次数
                        self.db.db.emoji.update_one(
                            {'_id': emoji['_id']},
                            {'$inc': {'usage_count': 1}}
                        )
                        return emoji['path']
                except StopIteration:
                    print(f"\033[1;31m[错误]\033[0m 数据库中没有任何表情")
                    return None
            
            return None
            
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 获取表情包失败: {str(e)}")
            return None


    async def get_emoji_for_text(self, text: str) -> Optional[str]:
        """根据文本内容获取相关表情包
        Args:
            text: 输入文本
        Returns:
            Optional[str]: 表情包文件路径，如果没有找到则返回None
        """
        try:
            self._ensure_db()
            # 获取情感标签
            emotions = await self._get_emotion_from_text(text)
            print("为  ‘"+ str(text) + "’  获取到的情感标签为：" + str(emotions))
            if not emotions:
                return None
                
            # 构建查询条件：标签匹配任一情感
            query = {'tags': {'$in': emotions}}
            
            print(f"\033[1;34m[调试]\033[0m 表情查询条件: {query}")
            print(f"\033[1;34m[调试]\033[0m 匹配到的情感: {emotions}")
            
            try:
                # 随机获取一个匹配的表情
                emoji = self.db.db.emoji.aggregate([
                    {'$match': query},
                    {'$sample': {'size': 1}}
                ]).next()
                print(f"\033[1;32m[成功]\033[0m 找到匹配的表情")
                if emoji and 'path' in emoji:
                    # 更新使用次数
                    self.db.db.emoji.update_one(
                        {'_id': emoji['_id']},
                        {'$inc': {'usage_count': 1}}
                    )
                    return emoji['path']
            except StopIteration:
                # 如果没有匹配的表情，从所有表情中随机选择一个
                print(f"\033[1;33m[提示]\033[0m 未找到匹配的表情，随机选择一个")
                try:
                    emoji = self.db.db.emoji.aggregate([
                        {'$sample': {'size': 1}}
                    ]).next()
                    if emoji and 'path' in emoji:
                        # 更新使用次数
                        self.db.db.emoji.update_one(
                            {'_id': emoji['_id']},
                            {'$inc': {'usage_count': 1}}
                        )
                        return emoji['path']
                except StopIteration:
                    print(f"\033[1;31m[错误]\033[0m 数据库中没有任何表情")
                    return None
            
            return None
            
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 获取表情包失败: {str(e)}")
            return None

    async def _get_emoji_tag(self, image_base64: str) -> str:
        """获取表情包的标签"""
        async with aiohttp.ClientSession() as session:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {llm_config.SILICONFLOW_API_KEY}"
            }
            
            payload = {
                "model": "deepseek-ai/deepseek-vl2",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": '这是一个表情包，请从"happy", "angry", "sad", "surprised", "disgusted", "fearful", "neutral"中选出1个情感标签。只输出标签，不要输出其他任何内容，只输出情感标签就好'
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 60,
                "temperature": 0.3
            }
            
            async with session.post(
                f"{llm_config.SILICONFLOW_BASE_URL}chat/completions",
                headers=headers,
                json=payload
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    if "choices" in result and len(result["choices"]) > 0:
                        tag_result = result["choices"][0]["message"]["content"].strip().lower()

                        valid_tags = ["happy", "angry", "sad", "surprised", "disgusted", "fearful", "neutral"]
                        for tag_match in valid_tags:
                            if tag_match in tag_result or tag_match == tag_result:
                                return tag_match
                        print(f"\033[1;33m[警告]\033[0m 无效的标签: {tag_match}, 跳过")
                else:
                    print(f"\033[1;31m[错误]\033[0m 获取标签失败, 状态码: {response.status}")
        
        print(f"\033[1;32m[调试信息]\033[0m 使用默认标签: neutral")
        return "skip"  # 默认标签

    async def scan_new_emojis(self):
        """扫描新的表情包"""
        try:
            emoji_dir = "data/emoji"
            os.makedirs(emoji_dir, exist_ok=True)

            # 获取所有jpg文件
            files_to_process = [f for f in os.listdir(emoji_dir) if f.endswith('.jpg')]
            
            for filename in files_to_process:
                # 检查是否已经注册过
                existing_emoji = self.db.db['emoji'].find_one({'filename': filename})
                if existing_emoji:
                    continue
                    
                image_path = os.path.join(emoji_dir, filename)
                # 读取图片数据
                with open(image_path, 'rb') as f:
                    image_data = f.read()
                
                # 将图片转换为base64
                image_base64 = base64.b64encode(image_data).decode('utf-8')
                
                # 获取表情包的情感标签
                tag = await self._get_emoji_tag(image_base64)
                if not tag == "skip":
                # 准备数据库记录
                    emoji_record = {
                        'filename': filename,
                        'path': image_path,
                        'tags': [tag],
                        'timestamp': int(time.time())
                    }
                    
                    # 保存到数据库
                    self.db.db['emoji'].insert_one(emoji_record)
                    print(f"\033[1;32m[成功]\033[0m 注册新表情包: {filename}")
                    print(f"标签: {tag}")
                else:
                    print(f"\033[1;33m[警告]\033[0m 跳过表情包: {filename}")

                
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 扫描表情包失败: {str(e)}")
            import traceback
            print(traceback.format_exc())

    async def _periodic_scan(self, interval_MINS: int = 10):
        """定期扫描新表情包"""
        while True:
            print(f"\033[1;36m[表情包]\033[0m 开始扫描新表情包...")
            await self.scan_new_emojis()
            await asyncio.sleep(interval_MINS * 60)  # 每600秒扫描一次

    def check_emoji_file_integrity(self):
        """检查表情包文件完整性
        如果文件已被删除，则从数据库中移除对应记录
        """
        try:
            self._ensure_db()
            # 获取所有表情包记录
            all_emojis = list(self.db.db.emoji.find())
            removed_count = 0
            total_count = len(all_emojis)
            
            for emoji in all_emojis:
                try:
                    if 'path' not in emoji:
                        print(f"\033[1;33m[提示]\033[0m 发现无效记录（缺少path字段），ID: {emoji.get('_id', 'unknown')}")
                        self.db.db.emoji.delete_one({'_id': emoji['_id']})
                        removed_count += 1
                        continue
                        
                    # 检查文件是否存在
                    if not os.path.exists(emoji['path']):
                        print(f"\033[1;33m[提示]\033[0m 表情包文件已被删除: {emoji['path']}")
                        # 从数据库中删除记录
                        result = self.db.db.emoji.delete_one({'_id': emoji['_id']})
                        if result.deleted_count > 0:
                            print(f"\033[1;32m[成功]\033[0m 成功删除数据库记录: {emoji['_id']}")
                            removed_count += 1
                        else:
                            print(f"\033[1;31m[错误]\033[0m 删除数据库记录失败: {emoji['_id']}")
                except Exception as item_error:
                    print(f"\033[1;31m[错误]\033[0m 处理表情包记录时出错: {str(item_error)}")
                    continue
            
            # 验证清理结果
            remaining_count = self.db.db.emoji.count_documents({})
            if removed_count > 0:
                print(f"\033[1;32m[成功]\033[0m 已清理 {removed_count} 个失效的表情包记录")
                print(f"\033[1;34m[统计]\033[0m 清理前总数: {total_count} | 清理后总数: {remaining_count}")
                # print(f"\033[1;34m[统计]\033[0m 应删除数量: {removed_count} | 实际删除数量: {total_count - remaining_count}")
                # 执行数据库压缩
                try:
                    self.db.db.command({"compact": "emoji"})
                    print(f"\033[1;32m[成功]\033[0m 数据库集合压缩完成")
                except Exception as compact_error:
                    print(f"\033[1;31m[错误]\033[0m 数据库压缩失败: {str(compact_error)}")
            else:
                print(f"\033[1;36m[表情包]\033[0m 已检查 {total_count} 个表情包记录")
                
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 检查表情包完整性失败: {str(e)}")
            import traceback
            print(f"\033[1;31m[错误追踪]\033[0m\n{traceback.format_exc()}")

    async def start_periodic_check(self, interval_MINS: int = 120):
        while True:
            self.check_emoji_file_integrity()
            await asyncio.sleep(interval_MINS * 60)



# 创建全局单例
emoji_manager = EmojiManager() 