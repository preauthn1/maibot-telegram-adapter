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

    async def generate_response(self, prompt: str) -> Tuple[str, str]:
        """根据输入的提示生成模型的异步响应"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # 构建请求体
        data = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            **self.params
        }

        # 发送请求到完整的chat/completions端点
        api_url = f"{self.base_url.rstrip('/')}/chat/completions"
        logger.info(f"发送请求到URL: {api_url}/{self.model_name}")  # 记录请求的URL

        max_retries = 3
        base_wait_time = 15

        for retry in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(api_url, headers=headers, json=data) as response:
                        if response.status == 429:
                            wait_time = base_wait_time * (2 ** retry)  # 指数退避
                            logger.warning(f"遇到请求限制(429)，等待{wait_time}秒后重试...")
                            await asyncio.sleep(wait_time)
                            continue

                        if response.status in [500, 503]:
                            logger.error(f"服务器错误: {response.status}")
                            raise RuntimeError("服务器负载过高，模型恢复失败QAQ")

                        response.raise_for_status()  # 检查其他响应状态

                        result = await response.json()
                        if "choices" in result and len(result["choices"]) > 0:
                            message = result["choices"][0]["message"]
                            content = message.get("content", "")
                            think_match = None
                            reasoning_content = message.get("reasoning_content", "")
                            if not reasoning_content:
                                think_match = re.search(r'(?:<think>)?(.*?)</think>', content, re.DOTALL)
                            if think_match:
                                reasoning_content = think_match.group(1).strip()
                            content = re.sub(r'(?:<think>)?.*?</think>', '', content, flags=re.DOTALL, count=1).strip()
                            return content, reasoning_content
                        return "没有返回结果", ""

            except Exception as e:
                if retry < max_retries - 1:  # 如果还有重试机会
                    wait_time = base_wait_time * (2 ** retry)
                    logger.error(f"[回复]请求失败，等待{wait_time}秒后重试... 错误: {str(e)}", exc_info=True)
                    await asyncio.sleep(wait_time)
                else:
                    logger.critical(f"请求失败: {str(e)}", exc_info=True)
                    logger.critical(f"请求头: {headers} 请求体: {data}")
                    raise RuntimeError(f"API请求失败: {str(e)}")

        logger.error("达到最大重试次数，请求仍然失败")
        raise RuntimeError("达到最大重试次数，API请求仍然失败")

    async def generate_response_for_image(self, prompt: str, image_base64: str) -> Tuple[str, str]:
        """根据输入的提示和图片生成模型的异步响应"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # 构建请求体
        def build_request_data(img_base64: str):
            return {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{img_base64}"
                                }
                            }
                        ]
                    }
                ],
                **self.params
            }


        # 发送请求到完整的chat/completions端点
        api_url = f"{self.base_url.rstrip('/')}/chat/completions"
        logger.info(f"发送请求到URL: {api_url}/{self.model_name}")  # 记录请求的URL

        max_retries = 3
        base_wait_time = 15

        current_image_base64 = image_base64
        current_image_base64 = compress_base64_image_by_scale(current_image_base64)

        for retry in range(max_retries):
            try:
                data = build_request_data(current_image_base64)
                async with aiohttp.ClientSession() as session:
                    async with session.post(api_url, headers=headers, json=data) as response:
                        if response.status == 429:
                            wait_time = base_wait_time * (2 ** retry)  # 指数退避
                            logger.warning(f"遇到请求限制(429)，等待{wait_time}秒后重试...")
                            await asyncio.sleep(wait_time)
                            continue

                        elif response.status == 413:
                            logger.warning("图片太大(413)，尝试压缩...")
                            current_image_base64 = compress_base64_image_by_scale(current_image_base64)
                            continue

                        response.raise_for_status()  # 检查其他响应状态

                        result = await response.json()
                        if "choices" in result and len(result["choices"]) > 0:
                            message = result["choices"][0]["message"]
                            content = message.get("content", "")
                            think_match = None
                            reasoning_content = message.get("reasoning_content", "")
                            if not reasoning_content:
                                think_match = re.search(r'(?:<think>)?(.*?)</think>', content, re.DOTALL)
                            if think_match:
                                reasoning_content = think_match.group(1).strip()
                            content = re.sub(r'(?:<think>)?.*?</think>', '', content, flags=re.DOTALL, count=1).strip()
                            return content, reasoning_content
                        return "没有返回结果", ""

            except Exception as e:
                if retry < max_retries - 1:  # 如果还有重试机会
                    wait_time = base_wait_time * (2 ** retry)
                    logger.error(f"[image回复]请求失败，等待{wait_time}秒后重试... 错误: {str(e)}", exc_info=True)
                    await asyncio.sleep(wait_time)
                else:
                    logger.critical(f"请求失败: {str(e)}", exc_info=True)
                    logger.critical(f"请求头: {headers} 请求体: {data}")
                    raise RuntimeError(f"API请求失败: {str(e)}")

        logger.error("达到最大重试次数，请求仍然失败")
        raise RuntimeError("达到最大重试次数，API请求仍然失败")

    async def generate_response_async(self, prompt: str) -> Union[str, Tuple[str, str]]:
        """异步方式根据输入的提示生成模型的响应"""
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

        # 发送请求到完整的 chat/completions 端点
        api_url = f"{self.base_url.rstrip('/')}/chat/completions"
        logger.info(f"Request URL: {api_url}")  # 记录请求的 URL

        max_retries = 3
        base_wait_time = 15

        async with aiohttp.ClientSession() as session:
            for retry in range(max_retries):
                try:
                    async with session.post(api_url, headers=headers, json=data) as response:
                        if response.status == 429:
                            wait_time = base_wait_time * (2 ** retry)  # 指数退避
                            logger.warning(f"遇到请求限制(429)，等待{wait_time}秒后重试...")
                            await asyncio.sleep(wait_time)
                            continue

                        response.raise_for_status()  # 检查其他响应状态

                        result = await response.json()
                        if "choices" in result and len(result["choices"]) > 0:
                            message = result["choices"][0]["message"]
                            content = message.get("content", "")
                            think_match = None
                            reasoning_content = message.get("reasoning_content", "")
                            if not reasoning_content:
                                think_match = re.search(r'(?:<think>)?(.*?)</think>', content, re.DOTALL)
                            if think_match:
                                reasoning_content = think_match.group(1).strip()
                            content = re.sub(r'(?:<think>)?.*?</think>', '', content, flags=re.DOTALL, count=1).strip()
                            return content, reasoning_content
                        return "没有返回结果", ""

                except Exception as e:
                    if retry < max_retries - 1:  # 如果还有重试机会
                        wait_time = base_wait_time * (2 ** retry)
                        logger.error(f"[回复]请求失败，等待{wait_time}秒后重试... 错误: {str(e)}")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"请求失败: {str(e)}")
                        logger.critical(f"请求头: {headers} 请求体: {data}")
                        return f"请求失败: {str(e)}", ""

            logger.error("达到最大重试次数，请求仍然失败")
            return "达到最大重试次数，请求仍然失败", ""



    def generate_response_for_image_sync(self, prompt: str, image_base64: str) -> Tuple[str, str]:
        """同步方法：根据输入的提示和图片生成模型的响应"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        image_base64=compress_base64_image_by_scale(image_base64)

        # 构建请求体
        data = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
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
            **self.params
        }

        # 发送请求到完整的chat/completions端点
        api_url = f"{self.base_url.rstrip('/')}/chat/completions"
        logger.info(f"发送请求到URL: {api_url}/{self.model_name}")  # 记录请求的URL

        max_retries = 2
        base_wait_time = 6

        for retry in range(max_retries):
            try:
                response = requests.post(api_url, headers=headers, json=data, timeout=30)

                if response.status_code == 429:
                    wait_time = base_wait_time * (2 ** retry)
                    logger.warning(f"遇到请求限制(429)，等待{wait_time}秒后重试...")
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()  # 检查其他响应状态

                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    message = result["choices"][0]["message"]
                    content = message.get("content", "")
                    think_match = None
                    reasoning_content = message.get("reasoning_content", "")
                    if not reasoning_content:
                        think_match = re.search(r'(?:<think>)?(.*?)</think>', content, re.DOTALL)
                    if think_match:
                        reasoning_content = think_match.group(1).strip()
                    content = re.sub(r'(?:<think>)?.*?</think>', '', content, flags=re.DOTALL, count=1).strip()
                    return content, reasoning_content
                return "没有返回结果", ""

            except Exception as e:
                if retry < max_retries - 1:  # 如果还有重试机会
                    wait_time = base_wait_time * (2 ** retry)
                    logger.error(f"[image_sync回复]请求失败，等待{wait_time}秒后重试... 错误: {str(e)}", exc_info=True)
                    time.sleep(wait_time)
                else:
                    logger.critical(f"请求失败: {str(e)}", exc_info=True)
                    logger.critical(f"请求头: {headers} 请求体: {data}")
                    raise RuntimeError(f"API请求失败: {str(e)}")

        logger.error("达到最大重试次数，请求仍然失败")
        raise RuntimeError("达到最大重试次数，API请求仍然失败")

    def get_embedding_sync(self, text: str) -> Union[list, None]:
        """同步方法：获取文本的embedding向量
        
        Args:
            text: 需要获取embedding的文本
            
        Returns:
            list: embedding向量，如果失败则返回None
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": self.model_name,
            "input": text,
            "encoding_format": "float"
        }

        api_url = f"{self.base_url.rstrip('/')}/embeddings"
        logger.info(f"发送请求到URL: {api_url}/{self.model_name}")  # 记录请求的URL

        max_retries = 2
        base_wait_time = 6

        for retry in range(max_retries):
            try:
                response = requests.post(api_url, headers=headers, json=data, timeout=30)

                if response.status_code == 429:
                    wait_time = base_wait_time * (2 ** retry)
                    logger.warning(f"遇到请求限制(429)，等待{wait_time}秒后重试...")
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()

                result = response.json()
                if 'data' in result and len(result['data']) > 0:
                    return result['data'][0]['embedding']
                return None

            except Exception as e:
                if retry < max_retries - 1:
                    wait_time = base_wait_time * (2 ** retry)
                    logger.error(f"[embedding_sync]请求失败，等待{wait_time}秒后重试... 错误: {str(e)}", exc_info=True)
                    time.sleep(wait_time)
                else:
                    logger.critical(f"embedding请求失败: {str(e)}", exc_info=True)
                    logger.critical(f"请求头: {headers} 请求体: {data}")
                    return None

        logger.error("达到最大重试次数，embedding请求仍然失败")
        return None

    async def get_embedding(self, text: str, model: str = "BAAI/bge-m3") -> Union[list, None]:
        """异步方法：获取文本的embedding向量
        
        Args:
            text: 需要获取embedding的文本
            model: 使用的模型名称，默认为"BAAI/bge-m3"
            
        Returns:
            list: embedding向量，如果失败则返回None
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": model,
            "input": text,
            "encoding_format": "float"
        }

        api_url = f"{self.base_url.rstrip('/')}/embeddings"
        logger.info(f"发送请求到URL: {api_url}/{self.model_name}")  # 记录请求的URL

        max_retries = 3
        base_wait_time = 15

        for retry in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(api_url, headers=headers, json=data) as response:
                        if response.status == 429:
                            wait_time = base_wait_time * (2 ** retry)
                            logger.warning(f"遇到请求限制(429)，等待{wait_time}秒后重试...")
                            await asyncio.sleep(wait_time)
                            continue

                        response.raise_for_status()

                        result = await response.json()
                        if 'data' in result and len(result['data']) > 0:
                            return result['data'][0]['embedding']
                        return None

            except Exception as e:
                if retry < max_retries - 1:
                    wait_time = base_wait_time * (2 ** retry)
                    logger.error(f"[embedding]请求失败，等待{wait_time}秒后重试... 错误: {str(e)}", exc_info=True)
                    await asyncio.sleep(wait_time)
                else:
                    logger.critical(f"embedding请求失败: {str(e)}", exc_info=True)
                    logger.critical(f"请求头: {headers} 请求体: {data}")
                    return None

        logger.error("达到最大重试次数，embedding请求仍然失败")
        return None

    def rerank_sync(self, query: str, documents: list, top_k: int = 5) -> list:
        """同步方法：使用重排序API对文档进行排序
        
        Args:
            query: 查询文本
            documents: 待排序的文档列表
            top_k: 返回前k个结果
            
        Returns:
            list: [(document, score), ...] 格式的结果列表
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": self.model_name,
            "query": query,
            "documents": documents,
            "top_n": top_k,
            "return_documents": True,
        }

        api_url = f"{self.base_url.rstrip('/')}/rerank"
        logger.info(f"发送请求到URL: {api_url}")

        max_retries = 2
        base_wait_time = 6

        for retry in range(max_retries):
            try:
                response = requests.post(api_url, headers=headers, json=data, timeout=30)

                if response.status_code == 429:
                    wait_time = base_wait_time * (2 ** retry)
                    logger.warning(f"遇到请求限制(429)，等待{wait_time}秒后重试...")
                    time.sleep(wait_time)
                    continue
                
                if response.status_code in [500, 503]:
                    wait_time = base_wait_time * (2 ** retry)
                    logger.error(f"服务器错误({response.status_code})，等待{wait_time}秒后重试...")
                    if retry < max_retries - 1:
                        time.sleep(wait_time)
                        continue
                    else:
                        # 如果是最后一次重试，尝试使用chat/completions作为备选方案
                        return self._fallback_rerank_with_chat(query, documents, top_k)

                response.raise_for_status()

                result = response.json()
                if 'results' in result:
                    return [(item["document"], item["score"]) for item in result["results"]]
                return []

            except Exception as e:
                if retry < max_retries - 1:
                    wait_time = base_wait_time * (2 ** retry)
                    logger.error(f"[rerank_sync]请求失败，等待{wait_time}秒后重试... 错误: {str(e)}", exc_info=True)
                    time.sleep(wait_time)
                else:
                    logger.critical(f"重排序请求失败: {str(e)}", exc_info=True)

        logger.error("达到最大重试次数，重排序请求仍然失败")
        return []

    async def rerank(self, query: str, documents: list, top_k: int = 5) -> list:
        """异步方法：使用重排序API对文档进行排序
        
        Args:
            query: 查询文本
            documents: 待排序的文档列表
            top_k: 返回前k个结果
            
        Returns:
            list: [(document, score), ...] 格式的结果列表
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": self.model_name,
            "query": query,
            "documents": documents,
            "top_n": top_k,
            "return_documents": True,
        }

        api_url = f"{self.base_url.rstrip('/')}/v1/rerank"
        logger.info(f"发送请求到URL: {api_url}")

        max_retries = 3
        base_wait_time = 15

        for retry in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(api_url, headers=headers, json=data) as response:
                        if response.status == 429:
                            wait_time = base_wait_time * (2 ** retry)
                            logger.warning(f"遇到请求限制(429)，等待{wait_time}秒后重试...")
                            await asyncio.sleep(wait_time)
                            continue

                        if response.status in [500, 503]:
                            wait_time = base_wait_time * (2 ** retry)
                            logger.error(f"服务器错误({response.status})，等待{wait_time}秒后重试...")
                            if retry < max_retries - 1:
                                await asyncio.sleep(wait_time)
                                continue
                            else:
                                # 如果是最后一次重试，尝试使用chat/completions作为备选方案
                                return await self._fallback_rerank_with_chat_async(query, documents, top_k)

                        response.raise_for_status()

                        result = await response.json()
                        if 'results' in result:
                            return [(item["document"], item["score"]) for item in result["results"]]
                        return []

            except Exception as e:
                if retry < max_retries - 1:
                    wait_time = base_wait_time * (2 ** retry)
                    logger.error(f"[rerank]请求失败，等待{wait_time}秒后重试... 错误: {str(e)}", exc_info=True)
                    await asyncio.sleep(wait_time)
                else:
                    logger.critical(f"重排序请求失败: {str(e)}", exc_info=True)
                    # 作为最后的备选方案，尝试使用chat/completions
                    return await self._fallback_rerank_with_chat_async(query, documents, top_k)

        logger.error("达到最大重试次数，重排序请求仍然失败")
        return []

    async def _fallback_rerank_with_chat_async(self, query: str, documents: list, top_k: int = 5) -> list:
        """当rerank API失败时的备选方案，使用chat/completions异步实现重排序
        
        Args:
            query: 查询文本
            documents: 待排序的文档列表
            top_k: 返回前k个结果
            
        Returns:
            list: [(document, score), ...] 格式的结果列表
        """
        try:
            logger.info("使用chat/completions作为重排序的备选方案")
            
            # 构建提示词
            prompt = f"""请对以下文档列表进行重排序，按照与查询的相关性从高到低排序。
查询: {query}

文档列表:
{documents}

请以JSON格式返回排序结果，格式为：
[{{"document": "文档内容", "score": 相关性分数}}, ...]
只返回JSON，不要其他任何文字。"""

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
                **self.params
            }

            api_url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, headers=headers, json=data) as response:
                    response.raise_for_status()
                    result = await response.json()
                    
                    if "choices" in result and len(result["choices"]) > 0:
                        message = result["choices"][0]["message"]
                        content = message.get("content", "")
                        try:
                            import json
                            parsed_content = json.loads(content)
                            if isinstance(parsed_content, list):
                                return [(item["document"], item["score"]) for item in parsed_content]
                        except:
                            pass
            return []
        except Exception as e:
            logger.error(f"备选方案也失败了: {str(e)}")
            return []
