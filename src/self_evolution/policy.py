"""会话级运行时策略加载器：只读已部署快照，不在对话中途刷新。"""

from __future__ import annotations

from pathlib import Path

from .registry import CandidateRegistry


class RuntimePolicyLoader:
    def __init__(self, registry_root: Path):
        self.registry = CandidateRegistry(registry_root)

    def snapshot(self) -> str | None:
        """在创建一次服务/会话时读取；调用方应保存返回值。"""
        return self.registry.read_active()

    @staticmethod
    def apply(system_prompt: str, policy: str | None) -> str:
        if not policy:
            return system_prompt
        return f"{system_prompt.rstrip()}\n\n【已批准的自演化对话策略】\n{policy.strip()}"
