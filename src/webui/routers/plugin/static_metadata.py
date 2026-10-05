"""不执行插件代码的配置元数据提取；仅支持可静态证明的声明。"""

from pathlib import Path
from typing import Any, Dict, Optional

import ast

_MAX_SOURCE_BYTES = 512 * 1024


def _read_tree(root: Path, name: str) -> ast.Module:
    path = root / name
    if path.is_symlink() or path.resolve().parent != root.resolve():
        raise ValueError("配置元数据路径不安全")
    if path.stat().st_size > _MAX_SOURCE_BYTES:
        raise ValueError("配置元数据文件过大")
    return ast.parse(path.read_text(encoding="utf-8"))


def _literal(node: ast.AST, constants: Dict[str, Any]) -> Any:
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    # literal_eval 不解析属性、调用、推导式，绝不执行插件表达式。
    return ast.literal_eval(node)


def _assignment(node: ast.AST) -> tuple[str, ast.AST] | None:
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
        return node.target.id, node.value
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id, node.value
    return None


def _annotation(node: ast.AST) -> tuple[str, Any]:
    if isinstance(node, ast.Name):
        types = {"bool": "boolean", "int": "integer", "float": "number", "str": "string"}
        if node.id in types:
            return types[node.id], None
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        if node.value.id == "Literal":
            values = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            return "string", [ast.literal_eval(value) for value in values]
        if node.value.id in {"List", "list"}:
            item_type, choices = _annotation(node.slice)
            return "array", {"item_type": item_type, "choices": choices}
        if node.value.id in {"Dict", "dict"}:
            return "object", None
    raise ValueError("配置字段类型不能静态解析")


def _field(node: ast.AnnAssign, constants: Dict[str, Any], order: int) -> Dict[str, Any]:
    if not isinstance(node.target, ast.Name) or not isinstance(node.value, ast.Call):
        raise ValueError("配置字段不是静态 Field 声明")
    call = node.value
    if not isinstance(call.func, ast.Name) or call.func.id != "Field" or any(k.arg is None for k in call.keywords):
        raise ValueError("配置字段不是受支持的 Field 声明")
    keywords = {key.arg: key.value for key in call.keywords}
    if set(keywords) - {"default", "default_factory", "description", "json_schema_extra", "ge", "le", "max_length", "pattern"}:
        raise ValueError("配置 Field 含未支持的静态约束")
    extra = _literal(keywords["json_schema_extra"], constants) if "json_schema_extra" in keywords else {}
    if not isinstance(extra, dict):
        raise ValueError("配置字段元数据不是静态字典")
    field_type, details = _annotation(node.annotation)
    name = node.target.id
    result: Dict[str, Any] = {
        "name": name, "type": field_type, "description": "", "label": name,
        "required": "default" not in keywords and "default_factory" not in keywords and not call.args,
        "hidden": False, "disabled": False, "order": order,
        "ui_type": {"boolean": "switch", "integer": "number", "number": "number", "array": "list", "object": "json"}.get(field_type, "text"),
        "rows": 3,
    }
    if "description" in keywords:
        result["description"] = _literal(keywords["description"], constants)
    if field_type == "array":
        result["item_type"] = details["item_type"]
        if details["choices"] is not None:
            result["choices"] = details["choices"]
            result["multiple"] = True
    elif details is not None:
        result["choices"] = details
    # 只复制 SDK 可展示的元数据，不允许插件覆盖 name/type/required 等结构。
    for key in ("label", "hidden", "disabled", "order", "placeholder", "hint", "input_type", "step", "pattern", "max_length", "rows", "group", "depends_on", "depends_value", "min_items", "max_items", "example", "i18n"):
        if key in extra:
            result[key] = extra[key]
    if "x-widget" in extra:
        result["ui_type"] = extra["x-widget"]
    if "x-icon" in extra:
        result["icon"] = extra["x-icon"]
    for source, target in (("ge", "min"), ("le", "max"), ("max_length", "max_length"), ("pattern", "pattern")):
        if source in keywords:
            result[target] = _literal(keywords[source], constants)
    if result.get("input_type") == "password":
        result["ui_type"] = "password"
    elif result.get("choices") is not None:
        result["ui_type"] = "select"
    # default 只能来自源码，不读取 TOML/current_config；密码字段不向客户端输出默认值。
    if result.get("input_type") != "password":
        if "default" in keywords:
            result["default"] = _literal(keywords["default"], constants)
        elif call.args:
            result["default"] = _literal(call.args[0], constants)
        elif "default_factory" in keywords:
            factory = keywords["default_factory"]
            if isinstance(factory, ast.Name) and factory.id in {"list", "dict"}:
                result["default"] = [] if factory.id == "list" else {}
            else:
                raise ValueError("配置默认值工厂不能静态解析")
    result['disabled'] = True
    return result


def read_static_plugin_schema(plugin_id: str, plugin_path: Path) -> Optional[Dict[str, Any]]:
    """读取 plugin.py → config_model → config.py，失败显式返回无元数据，不导入插件。

    支持 PluginConfigBase 的本地嵌套节、Field 字面量和 constants.py 字面常量。
    动态继承/工厂/类型不猜测；调用方须展示元数据缺失说明。
    """
    try:
        plugin_tree = _read_tree(plugin_path, "plugin.py")
        roots = {
            value.id
            for cls in plugin_tree.body if isinstance(cls, ast.ClassDef)
            for item in cls.body
            if (assignment := _assignment(item)) is not None
            for name, value in [assignment]
            if name == "config_model" and isinstance(value, ast.Name)
        }
        if len(roots) != 1:
            return None
        root_name = next(iter(roots))
        # 配置类型必须明确来自同目录 config 模块，不能冒用同名动态对象。
        if not any(isinstance(item, ast.ImportFrom) and item.level == 1 and item.module == "config"
                   and any(alias.name == root_name and alias.asname is None for alias in item.names)
                   for item in plugin_tree.body):
            return None
        tree = _read_tree(plugin_path, "config.py")
        constants: Dict[str, Any] = {}
        for item in tree.body:
            if isinstance(item, ast.ImportFrom) and item.level == 1 and item.module == "constants":
                local_constants: Dict[str, Any] = {}
                for declaration in _read_tree(plugin_path, "constants.py").body:
                    assignment = _assignment(declaration)
                    if assignment is not None:
                        name, value = assignment
                        try:
                            local_constants[name] = _literal(value, local_constants)
                        except (ValueError, TypeError):
                            continue
                for alias in item.names:
                    if alias.name in local_constants:
                        constants[alias.asname or alias.name] = local_constants[alias.name]
            assignment = _assignment(item)
            if assignment is not None:
                name, value = assignment
                try:
                    constants[name] = _literal(value, constants)
                except (ValueError, TypeError):
                    continue
        classes = {item.name: item for item in tree.body if isinstance(item, ast.ClassDef)}
        root = classes[root_name]
        if len(root.bases) != 1 or not isinstance(root.bases[0], ast.Name) or root.bases[0].id != "PluginConfigBase":
            return None
        sections: Dict[str, Any] = {}
        for declaration in root.body:
            if not isinstance(declaration, ast.AnnAssign) or not isinstance(declaration.target, ast.Name):
                continue
            if not isinstance(declaration.annotation, ast.Name) or declaration.annotation.id not in classes:
                raise ValueError("顶层配置不是受支持的静态配置节")
            call = declaration.value
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != "Field":
                raise ValueError("顶层配置不是 Field 声明")
            factories = [key.value for key in call.keywords if key.arg == "default_factory"]
            if len(factories) != 1 or not isinstance(factories[0], ast.Name) or factories[0].id != declaration.annotation.id:
                raise ValueError("顶层配置工厂不是声明的配置节")
            section = classes[declaration.annotation.id]
            if len(section.bases) != 1 or not isinstance(section.bases[0], ast.Name) or section.bases[0].id != "PluginConfigBase":
                raise ValueError("配置节存在动态或未知继承")
            section_name = declaration.target.id
            fields: Dict[str, Any] = {}
            metadata: Dict[str, Any] = {}
            for item in section.body:
                assignment = _assignment(item)
                if assignment is not None and assignment[0].startswith("__ui_"):
                    metadata[assignment[0]] = _literal(assignment[1], constants)
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and not item.target.id.startswith("_"):
                    fields[item.target.id] = _field(item, constants, len(fields))
            sections[section_name] = {
                "name": section_name, "title": metadata.get("__ui_label__", section_name),
                "description": ast.get_docstring(section) or "", "icon": metadata.get("__ui_icon__"),
                "order": metadata.get("__ui_order__", len(sections)), "collapsed": False, "fields": fields,
            }
        if not sections:
            return None
        return {"plugin_id": plugin_id, "plugin_info": {"name": plugin_id, "version": "", "description": "", "author": ""},
                "sections": sections, "layout": {"type": "auto", "tabs": []},
                "_note": "来自插件源码的静态配置元数据；未执行运行时校验", "metadata_source": "static"}
    except (OSError, SyntaxError, ValueError, TypeError, KeyError, RecursionError):
        return None
