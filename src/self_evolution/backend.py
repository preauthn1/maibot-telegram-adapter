"""MaiBot 配置模型后端：复用现有 model_config，保留完整请求/响应元数据。"""

from __future__ import annotations

import math
import os
import tomllib
from urllib.parse import urlparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Completion:
    text: str
    finish_reason: str | None
    raw: dict[str, Any]


class ConfiguredModelBackend:
    def __init__(self, config_path: Path, task_name: str = "planner"):
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        tasks = config.get("model_task_config", {})
        if not isinstance(tasks, dict):
            raise ValueError("model_task_config must be an object")
        task = tasks.get(task_name)
        if not isinstance(task, dict) or not task.get("model_list"):
            raise ValueError(f"missing model task: {task_name}")
        model_name = task["model_list"][0]
        model = next((item for item in config.get("models", []) if item.get("name") == model_name), None)
        provider_name = model.get("api_provider") if model else None
        provider = next((item for item in config.get("api_providers", []) if item.get("name") == provider_name), None)
        if not provider or not model:
            raise ValueError("configured model/provider not found")
        self.base_url = str(provider.get("base_url", "")).rstrip("/")
        parsed_url = urlparse(self.base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("model provider base_url must be an absolute HTTP(S) URL")
        self.model = str(model.get("model_identifier", model_name))
        self.provider_name = str(provider_name)
        self.api_key = os.environ.get(f"MAIBOT_EVOLUTION_API_KEY_{provider_name}") or str(provider.get("api_key", ""))
        self.timeout = float(provider.get("timeout", 120))
        self.max_tokens = int(task.get("max_tokens", 1200))
        self.temperature = float(task.get("temperature", .3))
        if not math.isfinite(self.timeout) or self.timeout <= 0 or self.timeout > 3600:
            raise ValueError("model timeout must be within (0, 3600]")
        if self.max_tokens <= 0 or self.max_tokens > 100_000:
            raise ValueError("model max_tokens is out of range")
        if not math.isfinite(self.temperature) or not 0 <= self.temperature <= 2:
            raise ValueError("model temperature must be within [0, 2]")
        self.extra_params: dict[str, Any] = {}
        if isinstance(model.get("extra_params"), dict):
            self.extra_params.update(model["extra_params"])
        if isinstance(task.get("extra_params"), dict):
            self.extra_params.update(task["extra_params"])
        if "reasoning_effort" in task:
            self.extra_params["reasoning_effort"] = task["reasoning_effort"]
        self.reasoning_effort = self.extra_params.get("reasoning_effort")
        if not self.base_url or not self.api_key or self.api_key.startswith("«redacted"):
            raise ValueError("model backend has no usable secret; set MAIBOT_EVOLUTION_API_KEY_<provider>")

    def complete_response(self, messages: list[dict[str, str]]) -> Completion:
        import httpx

        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": self.temperature, "max_tokens": self.max_tokens, "stream": False}
        protected = {"model", "messages", "stream", "tools", "response_format"}
        if protected.intersection(self.extra_params):
            raise ValueError("extra_params attempts to override protected completion fields")
        body.update(self.extra_params)
        response = httpx.post(self.base_url + "/chat/completions", headers={"Authorization": f"Bearer {self.api_key}"}, json=body, timeout=self.timeout)
        response.raise_for_status()
        payload: Any = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("choices"), list) or len(payload["choices"]) != 1:
            raise RuntimeError("model response has invalid choices")
        choice = payload["choices"][0]
        if not isinstance(choice, dict):
            raise RuntimeError("model response choice is invalid")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("model response message is invalid")
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("empty model response")
        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        if finish_reason == "length":
            raise RuntimeError("model response was truncated at max_tokens")
        return Completion(text.strip(), str(finish_reason) if finish_reason is not None else None, payload)

    def complete(self, messages: list[dict[str, str]]) -> str:
        return self.complete_response(messages).text
