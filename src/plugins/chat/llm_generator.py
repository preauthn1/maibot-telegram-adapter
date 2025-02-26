from typing import Dict, Any, List, Optional, Union, Tuple
from openai import OpenAI
from functools import partial
from .config import BotConfig
from ...common.database import Database
import random
import os
import aiohttp
from dotenv import load_dotenv
from .relationship_manager import relationship_manager

# 获取当前文件的绝对路径
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
load_dotenv(os.path.join(root_dir, '.env'))



class LLMResponseGenerator:
    def __init__(self, config: BotConfig):
        self.config = config
        self.API_KEY = os.getenv('SILICONFLOW_KEY')
        self.BASE_URL =os.getenv('SILICONFLOW_BASE_URL')
        self.client = OpenAI(
            api_key=self.API_KEY,
            base_url=self.BASE_URL
        )

        self.db = Database.get_instance()
        # 当前使用的模型类型
        self.current_model_type = 'r1'  # 默认使用 R1

    async def generate_response(self, text: str) -> Optional[str]:
        """根据当前模型类型选择对应的生成函数"""
        if random.random() < self.config.MODEL_R1_PROBABILITY:
            self.current_model_type = "r1"
        else:
            self.current_model_type = "v3"
        
        print(f"+++++++++++++++++麦麦{self.current_model_type}思考中+++++++++++++++++")
        if self.current_model_type == 'r1':
            model_response = await self._generate_v3_response(text)
        else:
            model_response = await self._generate_v3_response(text)
        # 打印情感标签
        print(f'麦麦的回复------------------------------是：{model_response}')
        
        return model_response

    async def _generate_r1_response(self, text: str) -> Optional[str]:
        """使用 DeepSeek-R1 模型生成回复"""
        messages = [{"role": "user", "content": text}]
        async with aiohttp.ClientSession() as session:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.API_KEY}"
            }
            payload = {
                "model": "Pro/deepseek-ai/DeepSeek-R1",
                "messages": messages,
                "stream": False,
                "max_tokens": 1024,
                "temperature": 0.8
            }
            async with session.post(f"{self.BASE_URL}/chat/completions", 
                                    headers=headers, 
                                    json=payload) as response:
                result = await response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    reasoning_content = result["choices"][0]["message"].get("reasoning_content", "")
                    print(f"Content: {content}")
                    print(f"Reasoning: {reasoning_content}")
                    return content
                
        return None

    async def _generate_v3_response(self, text: str) -> Optional[str]:
        """使用 DeepSeek-V3 模型生成回复"""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.API_KEY}"
        }
        
        payload = {
            "model": "Pro/deepseek-ai/DeepSeek-V3",
            "messages": [{"role": "user", "content": text}],
            "max_tokens": 1024,
            "temperature": 0.8
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.BASE_URL}/chat/completions", 
                                    headers=headers, 
                                    json=payload) as response:
                result = await response.json()
                
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    return content
                else:
                    print(f"[ERROR] V3 回复发送生成失败: {result}")
                
        return None

    
llm_response = LLMResponseGenerator(config=BotConfig())