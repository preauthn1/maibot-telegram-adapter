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
import asyncio
import time
from PIL import Image
import io
from loguru import logger
import traceback

from nonebot import get_driver
from ..chat.config import global_config
from ..models.utils_model import LLM_request
from ..chat.utils import get_embedding

driver = get_driver()
config = driver.config


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
        self.llm = LLM_request(model=global_config.vlm, temperature=0.3, max_tokens=1000)
        self.lm = LLM_request(model=global_config.llm_reasoning_minor, max_tokens=1000)
        
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
                logger.error(f"初始化表情管理器失败: {str(e)}")
                
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
            self.db.db.emoji.create_index([('embedding', '2dsphere')])
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
            logger.error(f"记录表情使用失败: {str(e)}")
            
    async def get_emoji_for_text(self, text: str) -> Optional[str]:
        """根据文本内容获取相关表情包
        Args:
            text: 输入文本
        Returns:
            Optional[str]: 表情包文件路径，如果没有找到则返回None
        """
        try:
            self._ensure_db()
            
            # 获取文本的embedding
            text_for_search= await self._get_kimoji_for_text(text)
            text_embedding = get_embedding(text_for_search)
            if not text_embedding:
                logger.error("无法获取文本的embedding")
                return None
            
            try:
                # 获取所有表情包
                all_emojis = list(self.db.db.emoji.find({}, {'_id': 1, 'path': 1, 'embedding': 1, 'discription': 1}))
                
                if not all_emojis:
                    logger.warning("数据库中没有任何表情包")
                    return None
                
                # 计算余弦相似度并排序
                def cosine_similarity(v1, v2):
                    if not v1 or not v2:
                        return 0
                    dot_product = sum(a * b for a, b in zip(v1, v2))
                    norm_v1 = sum(a * a for a in v1) ** 0.5
                    norm_v2 = sum(b * b for b in v2) ** 0.5
                    if norm_v1 == 0 or norm_v2 == 0:
                        return 0
                    return dot_product / (norm_v1 * norm_v2)
                
                # 计算所有表情包与输入文本的相似度
                emoji_similarities = [
                    (emoji, cosine_similarity(text_embedding, emoji.get('embedding', [])))
                    for emoji in all_emojis
                ]
                
                # 按相似度降序排序
                emoji_similarities.sort(key=lambda x: x[1], reverse=True)
                
                # 获取前3个最相似的表情包
                top_3_emojis = emoji_similarities[:3]
                
                if not top_3_emojis:
                    logger.warning("未找到匹配的表情包")
                    return None
                
                # 从前3个中随机选择一个
                selected_emoji, similarity = random.choice(top_3_emojis)
                
                if selected_emoji and 'path' in selected_emoji:
                    # 更新使用次数
                    self.db.db.emoji.update_one(
                        {'_id': selected_emoji['_id']},
                        {'$inc': {'usage_count': 1}}
                    )
                    logger.success(f"找到匹配的表情包: {selected_emoji.get('discription', '无描述')} (相似度: {similarity:.4f})")
                    return selected_emoji['path']
                    
            except Exception as search_error:
                logger.error(f"搜索表情包失败: {str(search_error)}")
                return None
            
            return None
            
        except Exception as e:
            logger.error(f"获取表情包失败: {str(e)}")
            return None

    async def _get_emoji_tag(self, image_base64: str) -> str:
        """获取表情包的标签"""
        try:
            prompt = '这是一个表情包，请从"happy", "angry", "sad", "surprised", "disgusted", "fearful", "neutral"中选出1个情感标签。只输出标签，不要输出其他任何内容，只输出情感标签就好'
            
            content, _ = await self.llm.generate_response_for_image(prompt, image_base64)
            tag_result = content.strip().lower()
            
            valid_tags = ["happy", "angry", "sad", "surprised", "disgusted", "fearful", "neutral"]
            for tag_match in valid_tags:
                if tag_match in tag_result or tag_match == tag_result:
                    return tag_match
            print(f"\033[1;33m[警告]\033[0m 无效的标签: {tag_result}, 跳过")
            
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 获取标签失败: {str(e)}")
            return "neutral"
        
        print(f"\033[1;32m[调试信息]\033[0m 使用默认标签: neutral")
        return "neutral"  # 默认标签

    async def _get_emoji_discription(self, image_base64: str) -> str:
        """获取表情包的标签"""
        try:
            prompt = '这是一个表情包，使用中文简洁的描述一下表情包的内容和表情包所表达的情感'
            
            content, _ = await self.llm.generate_response_for_image(prompt, image_base64)
            logger.debug(f"输出描述: {content}")
            return content
            
        except Exception as e:
            logger.error(f"获取标签失败: {str(e)}")
            return None
    
    async def _check_emoji(self, image_base64: str) -> str:
        try:
            prompt = f'这是一个表情包，请回答这个表情包是否满足\"{global_config.EMOJI_CHECK_PROMPT}\"的要求，是则回答是，否则回答否，不要出现任何其他内容'
            
            content, _ = await self.llm.generate_response_for_image(prompt, image_base64)
            logger.debug(f"输出描述: {content}")
            return content
            
        except Exception as e:
            logger.error(f"获取标签失败: {str(e)}")
            return None
        
    async def _get_kimoji_for_text(self, text:str):
        try:
            prompt = f'这是{global_config.BOT_NICKNAME}将要发送的消息内容:\n{text}\n若要为其配上表情包，请你输出这个表情包应该表达怎样的情感，应该给人什么样的感觉，不要太简洁也不要太长，注意不要输出任何对内容的分析内容，只输出\"一种什么样的感觉\"中间的形容词部分。'
            
            content, _ = await self.lm.generate_response_async(prompt)
            logger.info(f"输出描述: {content}")
            return content
            
        except Exception as e:
            logger.error(f"获取标签失败: {str(e)}")
            return None
        
    async def _compress_image(self, image_path: str, target_size: int = 0.8 * 1024 * 1024) -> Optional[str]:
        """压缩图片并返回base64编码
        Args:
            image_path: 图片文件路径
            target_size: 目标文件大小（字节），默认0.8MB
        Returns:
            Optional[str]: 成功返回base64编码的图片数据，失败返回None
        """
        try:
            file_size = os.path.getsize(image_path)
            if file_size <= target_size:
                # 如果文件已经小于目标大小，直接读取并返回base64
                with open(image_path, 'rb') as f:
                    return base64.b64encode(f.read()).decode('utf-8')
            
            # 打开图片
            with Image.open(image_path) as img:
                # 获取原始尺寸
                original_width, original_height = img.size
                
                # 计算缩放比例
                scale = min(1.0, (target_size / file_size) ** 0.5)
                
                # 计算新的尺寸
                new_width = int(original_width * scale)
                new_height = int(original_height * scale)
                
                # 创建内存缓冲区
                output_buffer = io.BytesIO()
                
                # 如果是GIF，处理所有帧
                if getattr(img, "is_animated", False):
                    frames = []
                    for frame_idx in range(img.n_frames):
                        img.seek(frame_idx)
                        new_frame = img.copy()
                        new_frame = new_frame.resize((new_width, new_height), Image.Resampling.LANCZOS)
                        frames.append(new_frame)
                    
                    # 保存到缓冲区
                    frames[0].save(
                        output_buffer,
                        format='GIF',
                        save_all=True,
                        append_images=frames[1:],
                        optimize=True,
                        duration=img.info.get('duration', 100),
                        loop=img.info.get('loop', 0)
                    )
                else:
                    # 处理静态图片
                    resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    
                    # 保存到缓冲区，保持原始格式
                    if img.format == 'PNG' and img.mode in ('RGBA', 'LA'):
                        resized_img.save(output_buffer, format='PNG', optimize=True)
                    else:
                        resized_img.save(output_buffer, format='JPEG', quality=95, optimize=True)
                
                # 获取压缩后的数据并转换为base64
                compressed_data = output_buffer.getvalue()
                logger.success(f"压缩图片: {os.path.basename(image_path)} ({original_width}x{original_height} -> {new_width}x{new_height})")
                
                return base64.b64encode(compressed_data).decode('utf-8')
                
        except Exception as e:
            logger.error(f"压缩图片失败: {os.path.basename(image_path)}, 错误: {str(e)}")
            return None
            
    async def scan_new_emojis(self):
        """扫描新的表情包"""
        try:
            emoji_dir = "data/emoji"
            os.makedirs(emoji_dir, exist_ok=True)

            # 获取所有支持的图片文件
            files_to_process = [f for f in os.listdir(emoji_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))]
            
            for filename in files_to_process:
                image_path = os.path.join(emoji_dir, filename)
                
                # 检查是否已经注册过
                existing_emoji = self.db.db['emoji'].find_one({'filename': filename})
                if existing_emoji:
                    continue
                
                # 压缩图片并获取base64编码
                image_base64 = await self._compress_image(image_path)
                if image_base64 is None:
                    os.remove(image_path)
                    continue
                
                # 获取表情包的描述
                discription = await self._get_emoji_discription(image_base64)
                check = await self._check_emoji(image_base64)
                if '是' not in check:
                    os.remove(image_path)
                    logger.info(f"描述: {discription}")
                    logger.info(f"其不满足过滤规则，被剔除 {check}")
                    continue
                logger.info(f"check通过 {check}")
                tag = await self._get_emoji_tag(image_base64)
                embedding = get_embedding(discription)
                if discription is not None:
                    # 准备数据库记录
                    emoji_record = {
                        'filename': filename,
                        'path': image_path,
                        'embedding':embedding,
                        'discription': discription,
                        'tag':tag,
                        'timestamp': int(time.time())
                    }
                    
                    # 保存到数据库
                    self.db.db['emoji'].insert_one(emoji_record)
                    logger.success(f"注册新表情包: {filename}")
                    logger.info(f"描述: {discription}")
                else:
                    logger.warning(f"跳过表情包: {filename}")
                
        except Exception as e:
            logger.error(f"扫描表情包失败: {str(e)}")
            logger.error(traceback.format_exc())
    
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
                        logger.warning(f"发现无效记录（缺少path字段），ID: {emoji.get('_id', 'unknown')}")
                        self.db.db.emoji.delete_one({'_id': emoji['_id']})
                        removed_count += 1
                        continue
                    
                    if 'embedding' not in emoji:
                        logger.warning(f"发现过时记录（缺少embedding字段），ID: {emoji.get('_id', 'unknown')}")
                        self.db.db.emoji.delete_one({'_id': emoji['_id']})
                        removed_count += 1
                        continue
                        
                    # 检查文件是否存在
                    if not os.path.exists(emoji['path']):
                        logger.warning(f"表情包文件已被删除: {emoji['path']}")
                        # 从数据库中删除记录
                        result = self.db.db.emoji.delete_one({'_id': emoji['_id']})
                        if result.deleted_count > 0:
                            logger.success(f"成功删除数据库记录: {emoji['_id']}")
                            removed_count += 1
                        else:
                            logger.error(f"删除数据库记录失败: {emoji['_id']}")
                except Exception as item_error:
                    logger.error(f"处理表情包记录时出错: {str(item_error)}")
                    continue
            
            # 验证清理结果
            remaining_count = self.db.db.emoji.count_documents({})
            if removed_count > 0:
                logger.success(f"已清理 {removed_count} 个失效的表情包记录")
                logger.info(f"清理前总数: {total_count} | 清理后总数: {remaining_count}")
            else:
                logger.info(f"已检查 {total_count} 个表情包记录")
                
        except Exception as e:
            logger.error(f"检查表情包完整性失败: {str(e)}")
            logger.error(traceback.format_exc())

    async def start_periodic_check(self, interval_MINS: int = 120):
        while True:
            self.check_emoji_file_integrity()
            await asyncio.sleep(interval_MINS * 60)



# 创建全局单例
emoji_manager = EmojiManager() 