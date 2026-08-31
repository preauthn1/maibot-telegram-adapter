"""核对插件声明的能力与实际调用的能力是否一致。

背景：``frequency.set_adjust`` 曾因未在 _manifest.json 声明而被
E_CAPABILITY_DENIED 拒绝，但异常被 except 吞成 warning，导致群权重
调度整个功能静默失效了一整轮提交都没被发现。

这个脚本用 AST 扫出所有 call_capability 的字面量参数，与 manifest
交叉核对，把同类问题一次性找干净。
"""

import ast
import json
from pathlib import Path

PLUGIN_DIR = Path("plugins/telegram_user_adapter")


class CapabilityVisitor(ast.NodeVisitor):
    """收集 call_capability("xxx") 里的字面量能力名。"""

    def __init__(self) -> None:
        self.found: list[tuple[str, int]] = []
        self.dynamic: list[int] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func
        name = getattr(func, "attr", None) or getattr(func, "id", None)
        if name == "call_capability" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                self.found.append((first.value, node.lineno))
            else:
                # 动态拼出来的能力名无法静态核对，单独标出来
                self.dynamic.append(node.lineno)
        else:
            # SDK 还提供了点式封装（如 ctx.maisaka.context.append），
            # 它们同样受 manifest 能力约束，必须一并识别，
            # 否则会误报"声明了但没用到"。
            dotted = self._dotted_name(func)
            if dotted:
                self.found.append((dotted, node.lineno))
        self.generic_visit(node)

    @staticmethod
    def _dotted_name(func: ast.expr) -> str | None:
        """把 ctx.maisaka.context.append 还原成 maisaka.context.append。

        Args:
            func: 调用节点的 func 部分。

        Returns:
            str | None: 去掉 ctx/self 前缀的点式能力名；不匹配时返回 None。
        """

        parts: list[str] = []
        node: ast.expr | None = func
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        parts.append(node.id)
        parts.reverse()

        # 只关心以 ctx 开头的链路，且至少要有 ctx.a.b.c 四段
        if len(parts) < 4 or parts[0] not in {"ctx", "self"}:
            return None
        if parts[0] == "self":
            if len(parts) < 5 or parts[1] != "ctx":
                return None
            parts = parts[1:]
        return ".".join(parts[1:])


manifest = json.loads((PLUGIN_DIR / "_manifest.json").read_text(encoding="utf-8"))
declared = set(manifest.get("capabilities", []))

used: dict[str, list[str]] = {}
dynamic_sites: list[str] = []

for py in sorted(PLUGIN_DIR.rglob("*.py")):
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except SyntaxError:
        continue
    visitor = CapabilityVisitor()
    visitor.visit(tree)
    for cap, lineno in visitor.found:
        used.setdefault(cap, []).append(f"{py.relative_to(PLUGIN_DIR)}:{lineno}")
    for lineno in visitor.dynamic:
        dynamic_sites.append(f"{py.relative_to(PLUGIN_DIR)}:{lineno}")

print(f"manifest 声明 {len(declared)} 项：")
for cap in sorted(declared):
    mark = "✅ 有调用" if cap in used else "⚠️  声明了但没用到"
    print(f"  {mark}  {cap}")

print(f"\n代码实际调用 {len(used)} 项：")
missing = []
for cap, sites in sorted(used.items()):
    if cap in declared:
        print(f"  ✅ 已声明  {cap}  ({len(sites)} 处)")
    else:
        missing.append(cap)
        print(f"  ❌ 未声明  {cap}")
        for s in sites:
            print(f"       {s}")

if dynamic_sites:
    print(f"\n⚠️  动态能力名（无法静态核对）{len(dynamic_sites)} 处：")
    for s in dynamic_sites:
        print(f"  {s}")

print()
if missing:
    print(f"❌ 发现 {len(missing)} 个未声明能力，会在运行时被拒绝：{missing}")
else:
    print("✅ 声明与调用完全一致")
