#!/usr/bin/env python3
"""Static audit for bug classes that actually bit us:

1. Sync helpers wrapped by an async-making decorator (e.g. @scoped_frequency)
   then used in boolean / truthy context -> coroutine always truthy.
2. Calls to coroutine functions without await (result used as value).
3. Decorators attached to a function different from upstream/backup.
"""
import ast
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
TARGETS = [BASE_DIR / "plugins", BASE_DIR / "src"]
ASYNC_MAKING_DECORATORS = {"scoped_frequency"}


def decorator_name(d: ast.expr) -> str:
    if isinstance(d, ast.Call):
        d = d.func
    if isinstance(d, ast.Attribute):
        return d.attr
    if isinstance(d, ast.Name):
        return d.id
    return ""


findings = []
for base in TARGETS:
    for path in base.rglob("*.py"):
        if "__pycache__" in path.parts or "node_modules" in path.parts or ".venv" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except Exception as exc:  # noqa: BLE001
            findings.append(f"PARSE {path}: {exc}")
            continue

        # collect per-class: async method names + sync-def-with-async-decorator
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)] + [tree]:
            body = cls.body
            async_names = set()
            for fn in body:
                if isinstance(fn, ast.AsyncFunctionDef):
                    async_names.add(fn.name)
                elif isinstance(fn, ast.FunctionDef):
                    decs = {decorator_name(d) for d in fn.decorator_list}
                    if decs & ASYNC_MAKING_DECORATORS:
                        async_names.add(fn.name)
                        findings.append(
                            f"SYNC_DEF_ASYNC_DECORATOR {path}:{fn.lineno} def {fn.name} decorated {sorted(decs & ASYNC_MAKING_DECORATORS)}"
                        )
            if not async_names:
                continue
            # find self.<async>() not awaited
            for node in ast.walk(cls):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "self"):
                    continue
                if f.attr not in async_names:
                    continue
                findings.append(("CALL", path, node, f.attr))

# resolve awaited-ness by parent mapping
out = []
parent_cache = {}
for item in findings:
    if isinstance(item, str):
        out.append(item)
        continue
    _, path, call, name = item
    tree = parent_cache.get(path)
    if tree is None:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for p in ast.walk(tree):
            for c in ast.iter_child_nodes(p):
                c._parent = p  # type: ignore[attr-defined]
        parent_cache[path] = tree
    # locate same call node in fresh tree by position
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and n.lineno == call.lineno and n.col_offset == call.col_offset:
            par = getattr(n, "_parent", None)
            if isinstance(par, ast.Await):
                break
            # passed to create_task / gather / ensure_future is fine
            if isinstance(par, ast.Call) and decorator_name(par.func) in {"create_task", "ensure_future", "gather", "wait_for", "shield", "run"}:
                break
            out.append(f"UNAWAITED {path}:{n.lineno} self.{name}(...) parent={type(par).__name__}")
            break

for line in sorted(set(out)):
    print(line)
print(f"TOTAL {len(set(out))}")
