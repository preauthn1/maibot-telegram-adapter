import os
import requests
from typing import Tuple, Union
import time

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
        
        max_retries = 3
        base_wait_time = 15  # 基础等待时间（秒）
        
        for retry in range(max_retries):
            try:
                response = requests.post(api_url, headers=headers, json=data)
                
                if response.status_code == 429:
                    wait_time = base_wait_time * (2 ** retry)  # 指数退避
                    print(f"遇到请求限制(429)，等待{wait_time}秒后重试...")
                    time.sleep(wait_time)
                    continue
                    
                response.raise_for_status()  # 检查其他响应状态
                
                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    reasoning_content = result["choices"][0]["message"].get("reasoning_content", "")
                    return content, reasoning_content
                return "没有返回结果", ""
                
            except requests.exceptions.RequestException as e:
                if retry < max_retries - 1:  # 如果还有重试机会
                    wait_time = base_wait_time * (2 ** retry)
                    print(f"请求失败，等待{wait_time}秒后重试... 错误: {str(e)}")
                    time.sleep(wait_time)
                else:
                    return f"请求失败: {str(e)}", ""
        
        return "达到最大重试次数，请求仍然失败", ""