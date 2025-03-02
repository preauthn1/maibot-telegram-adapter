import os
import requests
import aiohttp
from typing import Tuple, Union
from nonebot import get_driver
from src.plugins.chat.config import global_config
driver = get_driver()
config = driver.config

class LLMModel:
    # def __init__(self, model_name="deepseek-ai/DeepSeek-R1-Distill-Qwen-32B", **kwargs):
    def __init__(self, model_name=global_config.SILICONFLOW_MODEL_R1,api_using=None, **kwargs):
        if api_using == "deepseek":
            self.api_key = config.deep_seek_key
            self.base_url = config.deep_seek_base_url
            self.model_name = global_config.DEEPSEEK_MODEL_R1
        else:
            self.api_key = config.siliconflow_key
            self.base_url = config.siliconflow_base_url
            self.model_name = model_name
        self.params = kwargs

    def generate_response(self, prompt: str) -> Tuple[str, str]:
        """根据输入的提示生成模型的响应"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # 构建请求体
        data = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.9,
            **self.params
        }
        
        # 发送请求到完整的chat/completions端点
        api_url = f"{self.base_url.rstrip('/')}/chat/completions"
        
        try:
            response = requests.post(api_url, headers=headers, json=data)
            response.raise_for_status()  # 检查响应状态
            
            result = response.json()
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"]
                reasoning_content = result["choices"][0]["message"].get("reasoning_content", "")
                return content, reasoning_content  # 返回内容和推理内容
            return "没有返回结果", ""  # 返回两个值
                
        except Exception as e:
            return f"请求失败: {str(e)}", ""  # 返回错误信息和空字符串

# 示例用法
if __name__ == "__main__":
    model = LLMModel()  # 默认使用 DeepSeek-V3 模型
    prompt = "你好，你喜欢我吗？"
    result, reasoning = model.generate_response(prompt)
    print("回复内容:", result)
    print("推理内容:", reasoning)