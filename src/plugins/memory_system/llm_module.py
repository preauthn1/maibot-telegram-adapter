import os
import requests
from dotenv import load_dotenv
from typing import Tuple, Union

# 加载环境变量
load_dotenv()

class LLMModel:
    # def __init__(self, model_name="deepseek-ai/DeepSeek-R1-Distill-Qwen-32B", **kwargs):
    def __init__(self, model_name="Pro/deepseek-ai/DeepSeek-V3", **kwargs):
        self.model_name = model_name
        self.params = kwargs
        self.api_key = os.getenv("SILICONFLOW_KEY")
        self.base_url = os.getenv("SILICONFLOW_BASE_URL")

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
            "temperature": 0.5,
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
            
        except requests.exceptions.RequestException as e:
            return f"请求失败: {str(e)}", ""  # 返回错误信息和空字符串