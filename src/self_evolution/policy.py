"""会话级运行时策略加载器：支持受控热刷新与结构化候选解析（Fail-closed）。"""

from __future__ import annotations

import json
from pathlib import Path

from .registry import CandidateRegistry

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_self_evolution_path(relative_or_abs: Path | str = Path("data/self-evolution")) -> Path:
    """解析自演化数据路径：兼顾测试环境 chdir(tmp_path) 与生产环境固定项目根目录（Codex C5）。"""
    path = Path(relative_or_abs)
    if path.is_absolute():
        return path
    cwd_candidate = Path.cwd() / path
    proj_candidate = _PROJECT_ROOT / path
    # 若当前工作目录不是项目根，但存在专门创建的测试子目录（如 tmp_path/data/self-evolution），优先使用测试目录；
    # 否则一律锚定到 _PROJECT_ROOT，防止进程在含普通 ./data 的无关工作目录启动时写偏。
    if Path.cwd().resolve() != _PROJECT_ROOT and cwd_candidate.exists():
        return cwd_candidate
    return proj_candidate


class RuntimePolicyLoader:
    def __init__(self, registry_root: Path = Path("data/self-evolution")):
        resolved_root = resolve_self_evolution_path(registry_root)
        self.registry = CandidateRegistry(resolved_root)
        self._cached_signature: tuple | None = None
        self._cached_policy: str | None = None

    def snapshot(self) -> str | None:
        """读取当前激活策略；若磁盘上的 active_policy.txt 已更新或回滚，按文件签名自动刷新。"""
        active_path = self.registry.active
        try:
            stat = active_path.stat() if active_path.is_file() else None
            sig = (str(active_path), stat.st_ino, stat.st_mtime_ns, stat.st_size) if stat else None
        except OSError:
            sig = None
        if sig is not None and sig == self._cached_signature:
            return self._cached_policy
        self._cached_signature = sig
        self._cached_policy = self.registry.read_active()
        return self._cached_policy

    @staticmethod
    def render_policy_text(policy: str | None) -> str:
        """将已批准的候选内容渲染为安全的自然语言策略文本（拒绝把原始 JSON 元数据直接拼入 Prompt）。"""
        if not policy or not policy.strip():
            return ""
        stripped = policy.strip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except ValueError:
                return ""
            if not isinstance(parsed, dict):
                return ""
            kind = parsed.get("kind")
            if kind == "prompt_sections":
                sections = parsed.get("sections")
                if not isinstance(sections, dict):
                    return ""
                rendered = [
                    str(val).strip()
                    for _, val in sorted(sections.items())
                    if isinstance(val, str) and str(val).strip()
                ]
                return "\n\n".join(rendered)
            if kind == "tool_descriptions":
                # 工具描述候选由工具注册层消费，不把原始 JSON 注入对话 system prompt
                return ""
            return ""
        return stripped

    @classmethod
    def apply(cls, system_prompt: str, policy: str | None) -> str:
        rendered = cls.render_policy_text(policy)
        if not rendered:
            return system_prompt
        return f"{system_prompt.rstrip()}\n\n【已批准的自演化对话策略】\n{rendered}"
