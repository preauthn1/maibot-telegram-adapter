"""插件能力声明与调用的一致性测试。

背景：``frequency.set_adjust`` 未在 _manifest.json 声明，调用被
E_CAPABILITY_DENIED 拒绝，而异常在调用处被 except 成 warning，
导致群权重调度整整一轮提交都静默失效。

这个测试把"声明 vs 调用"的核对固化下来，新增能力时忘记声明会直接
挂测试，而不是等到线上才发现功能没生效。
"""

from __future__ import annotations

from pathlib import Path

import ast
import json

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "telegram_user_adapter"


class _CapabilityVisitor(ast.NodeVisitor):
    """收集能力调用点。"""

    def __init__(self) -> None:
        self.found: list[tuple[str, int]] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func
        name = getattr(func, "attr", None) or getattr(func, "id", None)
        if name == "call_capability" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                self.found.append((first.value, node.lineno))
        else:
            dotted = self._dotted_name(func)
            if dotted:
                self.found.append((dotted, node.lineno))
        self.generic_visit(node)

    @staticmethod
    def _dotted_name(func: ast.expr) -> str | None:
        """把 ctx.maisaka.context.append 还原为 maisaka.context.append。"""

        parts: list[str] = []
        node: ast.expr | None = func
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        parts.append(node.id)
        parts.reverse()

        if len(parts) < 4 or parts[0] not in {"ctx", "self"}:
            return None
        if parts[0] == "self":
            if len(parts) < 5 or parts[1] != "ctx":
                return None
            parts = parts[1:]
        return ".".join(parts[1:])


def _collect_used() -> dict[str, list[str]]:
    """扫出插件里实际调用的能力及位置。"""

    used: dict[str, list[str]] = {}
    for py in sorted(PLUGIN_DIR.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        visitor = _CapabilityVisitor()
        visitor.visit(tree)
        for cap, lineno in visitor.found:
            used.setdefault(cap, []).append(f"{py.relative_to(PLUGIN_DIR)}:{lineno}")
    return used


def _declared() -> set[str]:
    """读取 manifest 声明的能力。"""

    manifest = json.loads((PLUGIN_DIR / "_manifest.json").read_text(encoding="utf-8"))
    return set(manifest.get("capabilities", []))


def test_all_used_capabilities_are_declared() -> None:
    """⚠️ 核心：调用了但没声明的能力会在运行时被拒绝。"""

    declared = _declared()
    used = _collect_used()

    missing = {cap: sites for cap, sites in used.items() if cap not in declared}
    assert not missing, (
        f"以下能力被调用但未在 _manifest.json 声明，运行时会被 "
        f"E_CAPABILITY_DENIED 拒绝：{missing}"
    )


def test_frequency_capability_declared() -> None:
    """群权重调度依赖这个能力，缺了整个功能静默失效。"""

    assert "frequency.set_adjust" in _declared()


def test_no_unused_declarations() -> None:
    """声明了却没调用说明要么代码删了、要么声明写错了，都该清理。"""

    declared = _declared()
    used = set(_collect_used())

    unused = declared - used
    assert not unused, f"以下能力已声明但无调用点，应确认是否写错或已废弃：{unused}"
