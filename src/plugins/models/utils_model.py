import aiohttp
import asyncio
import requests
import time
import re
from typing import Tuple, Union
from nonebot import get_driver
from loguru import logger
from ..chat.config import global_config
from ..chat.utils_image import compress_base64_image_by_scale

driver = get_driver()
config = driver.config


class LLM_request:
    def __init__(self, model, **kwargs):
        # 将大写的配置键转换为小写并从config中获取实际值
        try:
            self.api_key = getattr(config, model["key"])
            self.base_url = getattr(config, model["base_url"])
        except AttributeError as e:
            logger.error(f"配置错误：找不到对应的配置项 - {str(e)}")
            raise ValueError(f"配置错误：找不到对应的配置项 - {str(e)}") from e
        self.model_name = model["name"]
        self.params = kwargs

    async def _execute_request(
            self,
            endpoint: str,
            prompt: str = None,
            image_base64: str = None,
            payload: dict = None,
            retry_policy: dict = None,
            response_handler: callable = None,
    ):
        """统一请求执行入口
        Args:
            endpoint: API端点路径 (如 "chat/completions")
            prompt: prompt文本
            image_base64: 图片的base64编码
            payload: 请求体数据
            is_async: 是否异步
            retry_policy: 自定义重试策略
                (示例: {"max_retries":3, "base_wait":15, "retry_codes":[429,500]})
            response_handler: 自定义响应处理器
        """
        # 合并重试策略
        default_retry = {
            "max_retries": 3, "base_wait": 15,
            "retry_codes": [429, 413, 500, 503],
            "abort_codes": [400, 401, 402, 403]}
        policy = {**default_retry, **(retry_policy or {})}

        # 常见Error Code Mapping
        error_code_mapping = {
            400: "参数不正确",
            401: "API key 错误，认证失败",
            402: "账号余额不足",
            403: "需要实名,或余额不足",
            404: "Not Found",
            429: "请求过于频繁，请稍后再试",
            500: "服务器内部故障",
            503: "服务器负载过高"
        }

        api_url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        logger.info(f"发送请求到URL: {api_url}{self.model_name}")

        # 构建请求体
        if image_base64:
            payload = await self._build_payload(prompt, image_base64)
        elif payload is None:
            payload = await self._build_payload(prompt)

        session_method = aiohttp.ClientSession()

        for retry in range(policy["max_retries"]):
            try:
                # 使用上下文管理器处理会话
                headers = await self._build_headers()

                async with session_method as session:
                    response = await session.post(api_url, headers=headers, json=payload)

                # 处理需要重试的状态码
                if response.status in policy["retry_codes"]:
                    wait_time = policy["base_wait"] * (2 ** retry)
                    logger.warning(f"错误码: {response.status}, 等待 {wait_time}秒后重试")
                    if response.status == 413:
                        logger.warning("请求体过大，尝试压缩...")
                        image_base64 = compress_base64_image_by_scale(image_base64)
                        payload = await self._build_payload(prompt, image_base64)
                    elif response.status in [500, 503]:
                        logger.error(f"错误码: {response.status} - {error_code_mapping.get(response.status)}")
                        raise RuntimeError("服务器负载过高，模型恢复失败QAQ")
                    else:
                        logger.warning(f"请求限制(429)，等待{wait_time}秒后重试...")

                    await asyncio.sleep(wait_time)
                    continue
                elif response.status in policy["abort_codes"]:
                    logger.error(f"错误码: {response.status} - {error_code_mapping.get(response.status)}")
                    raise RuntimeError(f"请求被拒绝: {error_code_mapping.get(response.status)}")

                response.raise_for_status()
                result = await response.json()

                # 使用自定义处理器或默认处理
                return response_handler(result) if response_handler else self._default_response_handler(result)

            except Exception as e:
                if retry < policy["max_retries"] - 1:
                    wait_time = policy["base_wait"] * (2 ** retry)
                    logger.error(f"请求失败，等待{wait_time}秒后重试... 错误: {str(e)}")
                    await asyncio.sleep(wait_time)
                else:
                    logger.critical(f"请求失败: {str(e)}")
                    logger.critical(f"请求头: {self._build_headers()} 请求体: {payload}")
                    raise RuntimeError(f"API请求失败: {str(e)}")

        logger.error("达到最大重试次数，请求仍然失败")
        raise RuntimeError("达到最大重试次数，API请求仍然失败")

    async def _build_payload(self, prompt: str, image_base64: str = None) -> dict:
        """构建请求体"""
        if image_base64:
            return {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                        ]
                    }
                ],
                "max_tokens": global_config.max_response_length,
                **self.params
            }
        else:
            return {
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": global_config.max_response_length,
                **self.params
            }

    def _default_response_handler(self, result: dict) -> Tuple:
        """默认响应解析"""
        if "choices" in result and result["choices"]:
            message = result["choices"][0]["message"]
            content = message.get("content", "")
            content, reasoning = self._extract_reasoning(content)
            reasoning_content = message.get("model_extra", {}).get("reasoning_content", "")
            if not reasoning_content:
                reasoning_content = reasoning

            return content, reasoning_content

        return "没有返回结果", ""

    def _extract_reasoning(self, content: str) -> tuple[str, str]:
        """CoT思维链提取"""
        match = re.search(r'(?:<think>)?(.*?)</think>', content, re.DOTALL)
        content = re.sub(r'(?:<think>)?.*?</think>', '', content, flags=re.DOTALL, count=1).strip()
        if match:
            reasoning = match.group(1).strip()
        else:
            reasoning = ""
        return content, reasoning

    async def _build_headers(self) -> dict:
        """构建请求头"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def generate_response(self, prompt: str) -> Tuple[str, str]:
        """根据输入的提示生成模型的异步响应"""

        content, reasoning_content = await self._execute_request(
            endpoint="/chat/completions",
            prompt=prompt
        )
        return content, reasoning_content

    async def generate_response_for_image(self, prompt: str, image_base64: str) -> Tuple[str, str]:
        """根据输入的提示和图片生成模型的异步响应"""

        content, reasoning_content = await self._execute_request(
            endpoint="/chat/completions",
            prompt=prompt,
            image_base64=image_base64
        )
        return content, reasoning_content

    async def generate_response_async(self, prompt: str) -> Union[str, Tuple[str, str]]:
        """异步方式根据输入的提示生成模型的响应"""
        # 构建请求体
        data = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.5,
            "max_tokens": global_config.max_response_length,
            **self.params
        }

        content, reasoning_content = await self._execute_request(
            endpoint="/chat/completions",
            payload=data,
            prompt=prompt
        )
        return content, reasoning_content

    async def get_embedding(self, text: str, model: str = "BAAI/bge-m3") -> Union[list, None]:
        """异步方法：获取文本的embedding向量
        
        Args:
            text: 需要获取embedding的文本
            model: 使用的模型名称，默认为"BAAI/bge-m3"
            
        Returns:
            list: embedding向量，如果失败则返回None
        """
        def embedding_handler(result):
            """处理响应"""
            if "data" in result and len(result["data"]) > 0:
                return result["data"][0].get("embedding", None)
            return None

        embedding = await self._execute_request(
            endpoint="/embeddings",
            prompt=text,
            payload={
                "model": model,
                "input": text,
                "encoding_format": "float"
            },
            retry_policy={
                "max_retries": 2,
                "base_wait": 6
            },
            response_handler=embedding_handler
        )
        return embedding
