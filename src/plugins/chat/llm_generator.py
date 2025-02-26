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
import subprocess
import os
import sys
import threading
import queue
import numpy as np
from dotenv import load_dotenv
from .relationship_manager import relationship_manager
from ..schedule.schedule_generator import bot_schedule
from .prompt_builder import prompt_builder
from .config import llm_config
from .willing_manager import willing_manager
from .utils import get_embedding, split_into_sentences, process_text_with_typos
import aiohttp

# 获取当前文件的绝对路径
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
load_dotenv(os.path.join(root_dir, '.env'))

class ReasoningWindow:
    def __init__(self):
        self.process = None
        self.message_queue = queue.Queue()
        self.is_running = False
        self.content_file = "reasoning_content.txt"
        
    def start(self):
        if self.process is None:
            # 创建用于显示的批处理文件
            with open("reasoning_window.bat", "w", encoding="utf-8") as f:
                f.write('@echo off\n')
                f.write('chcp 65001\n')  # 设置UTF-8编码
                f.write('title Magellan Reasoning Process\n')
                f.write('echo Waiting for reasoning content...\n')
                f.write(':loop\n')
                f.write('if exist "reasoning_update.txt" (\n')
                f.write('    type "reasoning_update.txt" >> "reasoning_content.txt"\n')
                f.write('    del "reasoning_update.txt"\n')
                f.write('    cls\n')
                f.write('    type "reasoning_content.txt"\n')
                f.write(')\n')
                f.write('timeout /t 1 /nobreak >nul\n')
                f.write('goto loop\n')
            
            # 清空内容文件
            with open(self.content_file, "w", encoding="utf-8") as f:
                f.write("")
            
            # 启动新窗口
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.process = subprocess.Popen(['cmd', '/c', 'start', 'reasoning_window.bat'], 
                                         shell=True, 
                                         startupinfo=startupinfo)
            self.is_running = True
            
            # 启动处理线程
            threading.Thread(target=self._process_messages, daemon=True).start()
    
    def _process_messages(self):
        while self.is_running:
            try:
                # 获取新消息
                text = self.message_queue.get(timeout=1)
                # 写入更新文件
                with open("reasoning_update.txt", "w", encoding="utf-8") as f:
                    f.write(text)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"处理推理内容时出错: {e}")
    
    def update_content(self, text: str):
        if self.is_running:
            self.message_queue.put(text)
    
    def stop(self):
        self.is_running = False
        if self.process:
            self.process.terminate()
            self.process = None
        # 清理文件
        for file in ["reasoning_window.bat", "reasoning_content.txt", "reasoning_update.txt"]:
            if os.path.exists(file):
                os.remove(file)

# 创建全局单例
reasoning_window = ReasoningWindow()

class LLMResponseGenerator:
    def __init__(self, config: BotConfig):
        self.config = config
        self.client = OpenAI(
            api_key=llm_config.SILICONFLOW_API_KEY,
            base_url=llm_config.SILICONFLOW_BASE_URL
        )

        self.db = Database.get_instance()
        reasoning_window.start()
        # 当前使用的模型类型
        self.current_model_type = 'r1'  # 默认使用 R1

    async def generate_response(self, message: Message) -> Optional[Union[str, List[str]]]:
        """根据当前模型类型选择对应的生成函数"""
        # 使用随机数选择模型
        rand = random.random()
        if rand < 0.6:  # 60%概率使用 R1
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
            reasoning_content = response.choices[0].message.reasoning_content
        else:
            return None
        # 更新推理窗口
        self._update_reasoning_window(message, prompt, reasoning_content, content, sender_name)
        
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
            # V3 模型没有 reasoning_content
            self._update_reasoning_window(message, prompt, "V3模型无推理过程", content, sender_name)
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
            reasoning_content = response.choices[0].message.reasoning_content
        else:
            return None
        # 更新推理窗口
        self._update_reasoning_window(message, prompt, reasoning_content, content, sender_name)
        
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

    def _update_reasoning_window(self, message, prompt, reasoning_content, content, sender_name):
        """更新推理窗口内容"""
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # 获取当前使用的模型名称
        model_name = {
            'r1': 'DeepSeek-R1',
            'v3': 'DeepSeek-V3',
            'r1_distill': 'DeepSeek-R1-Distill-Qwen-32B'
        }.get(self.current_model_type, '未知模型')
        
        display_text = (
            f"Time: {current_time}\n"
            f"Group: {message.group_name}\n"
            f"User: {sender_name}\n"
            f"Model: {model_name}\n"
            f"\033[1;32mMessage:\033[0m {message.processed_plain_text}\n\n"
            f"\033[1;32mPrompt:\033[0m \n{prompt}\n"
            f"\n-------------------------------------------------------"
            f"\n\033[1;32mReasoning Process:\033[0m\n{reasoning_content}\n"
            f"\n\033[1;32mResponse Content:\033[0m\n{content}\n"
            f"\n{'='*50}\n"
        )
        reasoning_window.update_content(display_text)

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
            
            return messages, emotion_tags
        
        return processed_response, emotion_tags

# 创建全局实例
llm_response = LLMResponseGenerator(config=BotConfig())