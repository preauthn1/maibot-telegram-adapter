from typing import Dict, Any, List, Optional, Union, Tuple
from openai import OpenAI
import asyncio
import requests
from functools import partial
from .message import Message
from .config import BotConfig
from ...common.database import Database
import random
import time
import os
import numpy as np
from dotenv import load_dotenv
from .relationship_manager import relationship_manager
from ..schedule.schedule_generator import bot_schedule
from .prompt_builder import prompt_builder
from .config import llm_config
from .utils import get_embedding, split_into_sentences, process_text_with_typos


# 获取当前文件的绝对路径
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
load_dotenv(os.path.join(root_dir, '.env'))

class LLMResponseGenerator:
    def __init__(self, config: BotConfig):
        self.config = config
        self.client = OpenAI(
            api_key=llm_config.SILICONFLOW_API_KEY,
            base_url=llm_config.SILICONFLOW_BASE_URL
        )

        self.db = Database.get_instance()
        
        # 当前使用的模型类型
        self.current_model_type = 'r1'  # 默认使用 R1

    async def generate_response(self, message: Message) -> Optional[Union[str, List[str]]]:
        """根据当前模型类型选择对应的生成函数"""
        # 使用随机数选择模型
        rand = random.random()
        if rand < 0.8:  # 60%概率使用 R1
            self.current_model_type = "r1"
        elif rand < 0.5:  # 20%概率使用 V3
            self.current_model_type = "v3"
        else:  # 20%概率使用 R1-Distill
            self.current_model_type = "r1_distill"
        
        print(f"+++++++++++++++++麦麦{self.current_model_type}思考中+++++++++++++++++")
        if self.current_model_type == 'r1':
            model_response = await self._generate_r1_response(message)
        elif self.current_model_type == 'v3':
            model_response = await self._generate_v3_response(message)
        else:
            model_response = await self._generate_r1_distill_response(message)
        
        # 打印情感标签
        print(f'麦麦的回复是：{model_response}')
        model_response, emotion = await self._process_response(model_response)
        
        if model_response:
            print(f"为 '{model_response}' 获取到的情感标签为：{emotion}")
        
        return model_response, emotion

    async def _generate_r1_response(self, message: Message) -> Optional[str]:
        """使用 DeepSeek-R1 模型生成回复"""
        # 获取群聊上下文
        group_chat = await self._get_group_chat_context(message)
        sender_name = message.user_nickname or f"用户{message.user_id}"
        if relationship_manager.get_relationship(message.user_id):
            relationship_value = relationship_manager.get_relationship(message.user_id).relationship_value
            print(f"\033[1;32m[关系管理]\033[0m 回复中_当前关系值: {relationship_value}")
        else:
            relationship_value = 0.0
        
        # 构建 prompt
        prompt = prompt_builder._build_prompt(
            message_txt=message.processed_plain_text,
            sender_name=sender_name,
            relationship_value=relationship_value,
            group_id=message.group_id
        )
        
        def create_completion():
            return self.client.chat.completions.create(
                model="Pro/deepseek-ai/DeepSeek-R1",
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                max_tokens=1024
            )
            
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, create_completion)
        if response.choices[0].message.content:
            content = response.choices[0].message.content
            # 获取推理内容
            reasoning_content = "模型思考过程：\n" + prompt
            if hasattr(response.choices[0].message, "reasoning"):
                reasoning_content = response.choices[0].message.reasoning or reasoning_content
            elif hasattr(response.choices[0].message, "reasoning_content"):
                reasoning_content = response.choices[0].message.reasoning_content or reasoning_content

            # 保存推理结果到数据库
            self.db.db.reasoning_logs.insert_one({
                'time': time.time(),
                'group_id': message.group_id,
                'user': sender_name,
                'message': message.processed_plain_text,
                'model': "DeepSeek-R1",
                'reasoning': reasoning_content,
                'response': content,
                'prompt': prompt
            })
        else:
            return None
        
        return content

    async def _generate_v3_response(self, message: Message) -> Optional[str]:
        """使用 DeepSeek-V3 模型生成回复"""
        # 获取群聊上下文
        group_chat = await self._get_group_chat_context(message)
        sender_name = message.user_nickname or f"用户{message.user_id}"
        
        if relationship_manager.get_relationship(message.user_id):
            relationship_value = relationship_manager.get_relationship(message.user_id).relationship_value
            print(f"\033[1;32m[关系管理]\033[0m 回复中_当前关系值: {relationship_value}")
        else:
            relationship_value = 0.0
        
        prompt = prompt_builder._build_prompt(message.processed_plain_text, sender_name, relationship_value, group_id=message.group_id)
        
        messages = [{"role": "user", "content": prompt}]
        
        loop = asyncio.get_event_loop()
        create_completion = partial(
            self.client.chat.completions.create,
            model="Pro/deepseek-ai/DeepSeek-V3",
            messages=messages,
            stream=False,
            max_tokens=1024,
            temperature=0.8
        )
        response = await loop.run_in_executor(None, create_completion)
        
        if response.choices[0].message.content:
            content = response.choices[0].message.content
            # 保存推理结果到数据库
            self.db.db.reasoning_logs.insert_one({
                'time': time.time(),
                'group_id': message.group_id,
                'user': sender_name,
                'message': message.processed_plain_text,
                'model': "DeepSeek-V3",
                'reasoning': "V3模型无推理过程",
                'response': content,
                'prompt': prompt
            })

            return content
        else:
            print(f"[ERROR] V3 回复发送生成失败: {response}")
            
        return None

    async def _generate_r1_distill_response(self, message: Message) -> Optional[str]:
        """使用 DeepSeek-R1-Distill-Qwen-32B 模型生成回复"""
        # 获取群聊上下文
        group_chat = await self._get_group_chat_context(message)
        sender_name = message.user_nickname or f"用户{message.user_id}"
        if relationship_manager.get_relationship(message.user_id):
            relationship_value = relationship_manager.get_relationship(message.user_id).relationship_value
            print(f"\033[1;32m[关系管理]\033[0m 回复中_当前关系值: {relationship_value}")
        else:
            relationship_value = 0.0
        
        # 构建 prompt
        prompt = prompt_builder._build_prompt(
            message_txt=message.processed_plain_text,
            sender_name=sender_name,
            relationship_value=relationship_value,
            group_id=message.group_id
        )
        
        def create_completion():
            return self.client.chat.completions.create(
                model="deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                max_tokens=1024
            )
            
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, create_completion)
        if response.choices[0].message.content:
            content = response.choices[0].message.content
            # 获取推理内容
            reasoning_content = "模型思考过程：\n" + prompt
            if hasattr(response.choices[0].message, "reasoning"):
                reasoning_content = response.choices[0].message.reasoning or reasoning_content
            elif hasattr(response.choices[0].message, "reasoning_content"):
                reasoning_content = response.choices[0].message.reasoning_content or reasoning_content

            # 保存推理结果到数据库
            self.db.db.reasoning_logs.insert_one({
                'time': time.time(),
                'group_id': message.group_id,
                'user': sender_name,
                'message': message.processed_plain_text,
                'model': "DeepSeek-R1-Distill",
                'reasoning': reasoning_content,
                'response': content,
                'prompt': prompt
            })
        else:
            return None
            
        
        return content

    async def _get_group_chat_context(self, message: Message) -> str:
        """获取群聊上下文"""
        recent_messages = self.db.db.messages.find(
            {"group_id": message.group_id}
        ).sort("time", -1).limit(15)
        
        messages_list = list(recent_messages)[::-1]
        group_chat = ""
        
        for msg_dict in messages_list:
            time_str = time.strftime("%m-%d %H:%M:%S", time.localtime(msg_dict['time']))
            display_name = msg_dict.get('user_nickname', f"用户{msg_dict['user_id']}")
            content = msg_dict.get('processed_plain_text', msg_dict['plain_text'])
            
            group_chat += f"[{time_str}] {display_name}: {content}\n"
            
        return group_chat

    async def _get_emotion_tags(self, content: str) -> List[str]:
        """提取情感标签"""
        try:
            prompt = f'''请从以下内容中，从"happy,angry,sad,surprised,disgusted,fearful,neutral"中选出最匹配的1个情感标签并输出
            只输出标签就好，不要输出其他内容:
            内容：{content}
            输出：
            '''
            
            messages = [{"role": "user", "content": prompt}]
            
            loop = asyncio.get_event_loop()
            create_completion = partial(
                self.client.chat.completions.create,
                model="Pro/deepseek-ai/DeepSeek-V3",
                messages=messages,
                stream=False,
                max_tokens=30,
                temperature=0.6
            )
            response = await loop.run_in_executor(None, create_completion)
            
            if response.choices[0].message.content:
                # 确保返回的是列表格式
                emotion_tag = response.choices[0].message.content.strip()
                return [emotion_tag]  # 将单个标签包装成列表返回
                
            return ["neutral"]  # 如果无法获取情感标签，返回默认值
            
        except Exception as e:
            print(f"获取情感标签时出错: {e}")
            return ["neutral"]  # 发生错误时返回默认值
    
    async def _process_response(self, content: str) -> Tuple[Union[str, List[str]], List[str]]:
        """处理响应内容，返回处理后的内容和情感标签"""
        if not content:
            return None, []
        
        # 检查回复是否过长（超过200个字符）
        if len(content) > 200:
            print(f"回复过长 ({len(content)} 字符)，返回默认回复")
            return "麦麦不知道哦", ["angry"]
        
        emotion_tags = await self._get_emotion_tags(content)
        
        # 添加错别字和处理标点符号
        processed_response = process_text_with_typos(content)
        
        # 处理长消息
        if len(processed_response) > 5:
            sentences = split_into_sentences(processed_response)
            print(f"分割后的句子: {sentences}")
            messages = []
            current_message = ""
            
            for sentence in sentences:
                if len(current_message) + len(sentence) <= 5:
                    current_message += ' '
                    current_message += sentence
                else:
                    if current_message:
                        messages.append(current_message.strip())
                    current_message = sentence
            
            if current_message:
                messages.append(current_message.strip())
            
            # 检查分割后的消息数量是否过多（超过3条）
            if len(messages) > 3:
                print(f"分割后消息数量过多 ({len(messages)} 条)，返回默认回复")
                return "麦麦不知道哦", ["angry"]
            
            return messages, emotion_tags
        
        return processed_response, emotion_tags

# 创建全局实例
llm_response = LLMResponseGenerator(config=BotConfig())