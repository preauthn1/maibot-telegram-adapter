from typing import Dict, Any, List, Optional, Union, Tuple
from openai import OpenAI
import asyncio
from functools import partial
from .message import Message
from .config import global_config
from ...common.database import Database
import random
import time
import numpy as np
from .relationship_manager import relationship_manager
from .prompt_builder import prompt_builder
from .config import global_config
from .utils import process_llm_response
from nonebot import get_driver

driver = get_driver()
config = driver.config


class LLMResponseGenerator:
    def __init__(self):
        if global_config.API_USING == "siliconflow":
            self.client = OpenAI(
                api_key=config.siliconflow_key,
                base_url=config.siliconflow_base_url
            )
        elif global_config.API_USING == "deepseek":
            self.client = OpenAI(
                api_key=config.deep_seek_key,
                base_url=config.deep_seek_base_url
            )
            
        self.db = Database.get_instance()
        
        # 当前使用的模型类型
        self.current_model_type = 'r1'  # 默认使用 R1

    async def generate_response(self, message: Message) -> Optional[Union[str, List[str]]]:
        """根据当前模型类型选择对应的生成函数"""
        # 从global_config中获取模型概率值
        model_r1_probability = global_config.MODEL_R1_PROBABILITY
        model_v3_probability = global_config.MODEL_V3_PROBABILITY
        model_r1_distill_probability = global_config.MODEL_R1_DISTILL_PROBABILITY

        # 生成随机数并根据概率选择模型
        rand = random.random()
        if rand < model_r1_probability:
            self.current_model_type = 'r1'
        elif rand < model_r1_probability + model_v3_probability:
            self.current_model_type = 'v3'
        else:
            self.current_model_type = 'r1_distill'  # 默认使用 R1-Distill


        print(f"+++++++++++++++++{global_config.BOT_NICKNAME}{self.current_model_type}思考中+++++++++++++++++")
        if self.current_model_type == 'r1':
            model_response = await self._generate_r1_response(message)
        elif self.current_model_type == 'v3':
            model_response = await self._generate_v3_response(message)
        else:
            model_response = await self._generate_r1_distill_response(message)
        
        # 打印情感标签
        print(f'{global_config.BOT_NICKNAME}的回复是：{model_response}')
        model_response, emotion = await self._process_response(model_response)
        
        if model_response:
            print(f"为 '{model_response}' 获取到的情感标签为：{emotion}")
            valuedict={
                'happy':0.5,'angry':-1,'sad':-0.5,'surprised':0.5,'disgusted':-1.5,'fearful':-0.25,'neutral':0.25
            }
            await relationship_manager.update_relationship_value(message.user_id, relationship_value=valuedict[emotion[0]])


        return model_response, emotion

    async def _generate_base_response(
        self, 
        message: Message, 
        model_name: str,
        model_params: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        sender_name = message.user_nickname or f"用户{message.user_id}"
        if message.user_cardname:
            sender_name=f"[({message.user_id}){message.user_nickname}]{message.user_cardname}"
        
        # 获取关系值
        if relationship_manager.get_relationship(message.user_id):
            relationship_value = relationship_manager.get_relationship(message.user_id).relationship_value
            print(f"\033[1;32m[关系管理]\033[0m 回复中_当前关系值: {relationship_value}")
        else:
            relationship_value = 0.0
        
            
        ''' 构建prompt '''
        prompt,prompt_check = prompt_builder._build_prompt(
            message_txt=message.processed_plain_text,
            sender_name=sender_name,
            relationship_value=relationship_value,
            group_id=message.group_id
        )
        
        
        # 设置默认参数
        default_params = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": 2048,
            "temperature": 0.7
        }

        default_params_check = {
            "model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
            "messages": [{"role": "user", "content": prompt_check}],
            "stream": False,
            "max_tokens": 2048,
            "temperature": 0.7
        }

        default_params_check = {
            "model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
            "messages": [{"role": "user", "content": prompt_check}],
            "stream": False,
            "max_tokens": 1024,
            "temperature": 0.7
        }

        default_params_check = {
            "model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
            "messages": [{"role": "user", "content": prompt_check}],
            "stream": False,
            "max_tokens": 1024,
            "temperature": 0.7
        }
        
        # 更新参数
        if model_params:
            default_params.update(model_params)
        
        
        def create_completion():
            return self.client.chat.completions.create(**default_params)
        
        def create_completion_check():
            return self.client.chat.completions.create(**default_params_check)

        loop = asyncio.get_event_loop()

        # 读空气模块
        air = 0
        reasoning_content_check=''
        content_check=''
        if global_config.enable_kuuki_read:
            response_check = await loop.run_in_executor(None, create_completion_check)
            if response_check:
                reasoning_content_check = ""
                if hasattr(response_check.choices[0].message, "reasoning"):
                    reasoning_content_check = response_check.choices[0].message.reasoning or reasoning_content_check
                elif hasattr(response_check.choices[0].message, "reasoning_content"):
                    reasoning_content_check = response_check.choices[0].message.reasoning_content or reasoning_content_check
                content_check = response_check.choices[0].message.content
                print(f"\033[1;32m[读空气]\033[0m 读空气结果为{content_check}")
                if 'yes' not in content_check.lower():
                    air = 1
        #稀释读空气的判定
        if air == 1 and random.random() < 0.3:
            self.db.db.reasoning_logs.insert_one({
                'time': time.time(),
                'group_id': message.group_id,
                'user': sender_name,
                'message': message.processed_plain_text,
                'model': model_name,
                'reasoning_check': reasoning_content_check,
                'response_check': content_check,
                'reasoning': "",
                'response': "",
                'prompt': prompt,
                'prompt_check': prompt_check,
                'model_params': default_params
            })
            return None
        
        
        
            

        response = await loop.run_in_executor(None, create_completion)
        
        # 检查响应内容
        if not response:
            print("请求未返回任何内容")
            return None
        
        if not response.choices or not response.choices[0].message.content:
            print("请求返回的内容无效:", response)
            return None
            
        content = response.choices[0].message.content
        
        # 获取推理内容
        reasoning_content = ""
        if hasattr(response.choices[0].message, "reasoning"):
            reasoning_content = response.choices[0].message.reasoning or reasoning_content
        elif hasattr(response.choices[0].message, "reasoning_content"):
            reasoning_content = response.choices[0].message.reasoning_content or reasoning_content
            
        # 保存到数据库
        self.db.db.reasoning_logs.insert_one({
            'time': time.time(),
            'group_id': message.group_id,
            'user': sender_name,
            'message': message.processed_plain_text,
            'model': model_name,
            'reasoning_check': reasoning_content_check,
            'response_check': content_check,
            'reasoning': reasoning_content,
            'response': content,
            'prompt': prompt,
            'prompt_check': prompt_check,
            'model_params': default_params
        })
        
        return content

    async def _generate_r1_response(self, message: Message) -> Optional[str]:
        """使用 DeepSeek-R1 模型生成回复"""
        if global_config.API_USING == "deepseek":
            return await self._generate_base_response(
                message, 
                "deepseek-reasoner",
                {"temperature": 0.7, "max_tokens": 2048}
            )
        else:
            return await self._generate_base_response(
                message, 
                "Pro/deepseek-ai/DeepSeek-R1",
                {"temperature": 0.7, "max_tokens": 2048}
            )

    async def _generate_v3_response(self, message: Message) -> Optional[str]:
        """使用 DeepSeek-V3 模型生成回复"""
        if global_config.API_USING == "deepseek":
            return await self._generate_base_response(
                message, 
                "deepseek-chat",
                {"temperature": 0.8, "max_tokens": 2048}
            )
        else:
            return await self._generate_base_response(
                message, 
                "Pro/deepseek-ai/DeepSeek-V3",
                {"temperature": 0.8, "max_tokens": 2048}
            )

    async def _generate_r1_distill_response(self, message: Message) -> Optional[str]:
        """使用 DeepSeek-R1-Distill-Qwen-32B 模型生成回复"""
        return await self._generate_base_response(
            message, 
            "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
            {"temperature": 0.7, "max_tokens": 2048}
        )

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
            cardname = msg_dict.get('user_cardname', f"用户{msg_dict['user_id']}")
            display_name = f"[({msg_dict['user_id']}){display_name}]{cardname}"
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
            if global_config.API_USING == "deepseek":
                model = "deepseek-chat"
            else:
                model = "Pro/deepseek-ai/DeepSeek-V3"
            create_completion = partial(
                self.client.chat.completions.create,
                model=model,
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
    
    async def _process_response(self, content: str) -> Tuple[List[str], List[str]]:
        """处理响应内容，返回处理后的内容和情感标签"""
        if not content:
            return None, []
        
        emotion_tags = await self._get_emotion_tags(content)
    
        processed_response = process_llm_response(content)
        
        return processed_response, emotion_tags

# 创建全局实例
llm_response = LLMResponseGenerator()