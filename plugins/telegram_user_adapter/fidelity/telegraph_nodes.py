# SPDX-License-Identifier: GPL-3.0-only
# Modified 2026-10-06; see LONGTEXT-NOTICES.md for upstream provenance.
"""Bounded CommonMark subset -> Telegraph nodes; never HTML or remote media."""
from __future__ import annotations

import ipaddress
import json
import re
from urllib.parse import unquote, urlsplit

MAX_INPUT_BYTES = 32000
MAX_TOKENS = 4096
MAX_NODES = 1024
MAX_DEPTH = 16
MAX_JSON_BYTES = 48000
FORMATS = ("plain", "markdown")
ALLOWED = frozenset("p strong em s code pre a ul ol li blockquote h3 h4 br hr".split())


def validate_format(format: str) -> str:
    if not isinstance(format, str) or format not in FORMATS:
        raise ValueError("format must be exactly plain or markdown")
    return format


def safe_url(url: str | None) -> bool:
    """Only explicit HTTP(S) links; no credentials/local literals/obfuscation."""
    if not isinstance(url, str) or len(url) > 2048:
        return False
    decoded = url
    for _ in range(3):
        if re.search(r"[\s\x00-\x20\x7f-\x9f\\<>]", decoded):
            return False
        decoded = unquote(decoded)
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme not in ("https", "http") or not parts.netloc or parts.username is not None or parts.password is not None:
            return False
        if parts.port not in (None, 80, 443) or not host or "%" in parts.netloc:
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            pass
        host = host.encode("idna").decode("ascii").lower()
        if host.endswith((".local", ".localhost", ".internal", ".test", ".invalid")):
            return False
        labels = host.split(".")
        return len(labels) >= 2 and not labels[-1].isdigit() and all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
        )
    except (ValueError, UnicodeError):
        return False


def validate_nodes(nodes: list) -> list:
    stack = [(node, 1) for node in nodes]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise ValueError("Telegraph tree exceeds node/depth budget")
        if isinstance(node, str):
            continue
        if not isinstance(node, dict) or node.get("tag") not in ALLOWED or set(node) - {"tag", "children", "attrs"}:
            raise ValueError("Unsafe Telegraph node")
        attrs = node.get("attrs", {})
        if attrs and (node["tag"] != "a" or set(attrs) != {"href"} or not safe_url(attrs["href"])):
            raise ValueError("Unsafe Telegraph attributes")
        children = node.get("children", [])
        if not isinstance(children, list):
            raise ValueError("Invalid children")
        stack.extend((child, depth + 1) for child in children)
    if len(json.dumps(nodes, ensure_ascii=False).encode()) > MAX_JSON_BYTES:
        raise ValueError("Telegraph serialized tree exceeds budget")
    return nodes


def render_nodes(text: str, format: str = "plain") -> list:
    validate_format(format)
    if not isinstance(text, str) or not text.strip() or len(text.encode()) > MAX_INPUT_BYTES:
        raise ValueError("Invalid or oversized publication text")
    if format == "plain":
        return validate_nodes([{"tag": "p", "children": [text]}])
    # Deliberately separate from md_out: its HTML/Telegram entity extensions
    # must never become the public-page security boundary. Same parser family.
    from markdown_it import MarkdownIt
    tokens = MarkdownIt("commonmark", {"html": False, "maxNesting": MAX_DEPTH}).enable("strikethrough").parse(text)
    roots: list = []
    lists = [roots]
    opened = []
    count = 0
    tags = {"paragraph": "p", "strong": "strong", "em": "em", "s": "s",
            "bullet_list": "ul", "ordered_list": "ol", "list_item": "li",
            "blockquote": "blockquote", "link": "a"}

    def walk(items):
        nonlocal count
        for token in items:
            count += 1
            if count > MAX_TOKENS:
                raise ValueError("Markdown token budget exceeded")
            kind = token.type
            if kind == "inline":
                walk(token.children or [])
            elif token.nesting == 1:
                base = kind.removesuffix("_open")
                tag = ("h3" if token.tag in ("h1", "h2", "h3") else "h4") if base == "heading" else tags.get(base)
                if tag is None:
                    raise ValueError("Unsupported Markdown construct")
                href = token.attrGet("href") if tag == "a" else None
                if tag == "a" and not safe_url(href):
                    opened.append(False)  # retain label only, never unsafe href
                    continue
                node = {"tag": tag, "children": []}
                if href:
                    node["attrs"] = {"href": href}
                lists[-1].append(node)
                lists.append(node["children"])
                opened.append(True)
                if len(lists) > MAX_DEPTH:
                    raise ValueError("Markdown depth budget exceeded")
            elif token.nesting == -1:
                if not opened:
                    raise ValueError("Unbalanced Markdown")
                if opened.pop():
                    lists.pop()
            elif kind in ("text", "html_inline", "html_block"):
                lists[-1].append(token.content)
            elif kind in ("fence", "code_block", "code_inline"):
                lists[-1].append({"tag": "code" if kind == "code_inline" else "pre", "children": [token.content]})
            elif kind in ("softbreak", "hardbreak"):
                lists[-1].append("\n" if kind == "softbreak" else {"tag": "br"})
            elif kind == "hr":
                lists[-1].append({"tag": "hr"})
            elif kind == "image":
                # Alt text only; no src node, fetch, embed, or clickable image URL.
                lists[-1].append(token.content)
            else:
                raise ValueError("Unsupported Markdown token")
    walk(tokens)
    if opened:
        raise ValueError("Unbalanced Markdown")
    return validate_nodes(roots)
