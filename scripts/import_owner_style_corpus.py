"""导入操作员确认的本人语料；默认只校验，绝不从自动出站推定真人来源。

输入为 JSONL，每行：chat_id、message_id、sender_id、text、authorship。
authorship 必须显式为 owner_authored；这只是操作员声明，不是作者身份认证。
运行时不导入 MaiBot，不连接平台，不改聊天路由或人工画像。
"""
from pathlib import Path
from typing import Any, Dict, List

import argparse
import fcntl
import hashlib
import json
import os
import re
import tempfile


SOURCE = "operator_attested_owner"


def validate_rows(raw: str, owner_id: str) -> List[Dict[str, Any]]:
    """全量验证后才允许发布；冲突编号及自动生成标记一律拒绝。"""
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise ValueError("owner_id 必须非空")
    records = {}
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            raise ValueError(f"第 {number} 行不是有效 JSON") from None
        if not isinstance(row, dict):
            raise ValueError(f"第 {number} 行必须为对象")
        for key in ("chat_id", "message_id", "sender_id", "text"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"第 {number} 行字段 {key} 必须是非空字符串")
        if not re.fullmatch(r"-?\d+(?:::tg-topic::mt=\d+)?", row["chat_id"]):
            raise ValueError(f"第 {number} 行 chat_id 格式无效")
        if row["sender_id"] != owner_id:
            raise ValueError(f"第 {number} 行作者与指定账号不同")
        if row.get("authorship") != "owner_authored":
            raise ValueError(f"第 {number} 行缺少本人创作声明")
        if row.get("direction") == "out" or row.get("source") in ("bot_output", "model_generated"):
            raise ValueError(f"第 {number} 行包含自动出站或模型来源标记")
        if "generated" in row and row["generated"] is not False:
            raise ValueError(f"第 {number} 行 generated 必须显式为 false")
        item = {key: row[key] for key in ("chat_id", "message_id", "sender_id", "text")}
        item.update(schema_version=1, source=SOURCE)
        identity = (item["chat_id"], item["message_id"])
        if identity in records and records[identity] != item:
            raise ValueError(f"第 {number} 行同一消息编号出现冲突")
        records[identity] = item
    if not records:
        raise ValueError("语料为空")
    return list(records.values())


def publish_corpus(data_dir: Path, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """锁内合并并原子替换；历史冲突不覆盖，失败不发布部分语料。"""
    if not rows:
        raise ValueError("语料为空")
    owner_id = rows[0].get("sender_id") if isinstance(rows[0], dict) else None
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise ValueError("语料作者无效")
    if any(not isinstance(item, dict) or item.get("source") != SOURCE
           or type(item.get("schema_version")) is not int or item["schema_version"] != 1 for item in rows):
        raise ValueError("语料来源与版本无效")
    # 公共写入函数也校验，不依赖调用方一定经过 CLI。
    rows = validate_rows("\n".join(json.dumps({**item, "authorship": "owner_authored"}) for item in rows), owner_id)
    directory = data_dir / "style_corpus"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / "owner_verified.jsonl"
    if directory.is_symlink() or target.is_symlink():
        raise ValueError("语料目录与文件不得为符号链接")
    lock_fd = os.open(directory / ".import.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    temporary = None
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        existing = {}
        if target.exists():
            for line in target.read_text(encoding="utf-8").splitlines():
                item = json.loads(line)
                if not isinstance(item, dict) or item.get("schema_version") != 1 or item.get("source") != SOURCE:
                    raise ValueError("已有语料格式不匹配，未写入")
                if any(not isinstance(item.get(k), str) or not item[k].strip()
                       for k in ("chat_id", "message_id", "sender_id", "text")):
                    raise ValueError("已有语料字段无效，未写入")
                key = (item["chat_id"], item["message_id"])
                if key in existing and existing[key] != item:
                    raise ValueError("已有语料编号冲突，未写入")
                existing[key] = item
        before = len(existing)
        for item in rows:
            key = (item["chat_id"], item["message_id"])
            if key in existing and existing[key] != item:
                raise ValueError("导入内容与已有消息冲突，未写入")
            existing[key] = item
        payload = "".join(json.dumps(existing[key], ensure_ascii=False, sort_keys=True) + "\n"
                          for key in sorted(existing))
        encoded = payload.encode("utf-8")
        changed = not target.exists() or target.read_bytes() != encoded
        if changed:
            with tempfile.NamedTemporaryFile(mode="wb", dir=directory, prefix=".corpus-", delete=False) as handle:
                temporary = handle.name
                os.fchmod(handle.fileno(), 0o600)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            temporary = None
        return {"total": len(existing), "added": len(existing) - before, "changed": changed,
                "sha256": hashlib.sha256(encoded).hexdigest(), "path": str(target)}
    finally:
        if temporary is not None:
            os.unlink(temporary)
        os.close(lock_fd)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--owner-id", required=True)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="默认只校验；此选项才发布语料")
    parser.add_argument("--attest-owner-authored", action="store_true", help="确认输入由本人创作而非模型代写")
    args = parser.parse_args()
    if args.apply and not args.attest_owner_authored:
        parser.error("写入需要 --attest-owner-authored")
    rows = validate_rows(args.input.read_text(encoding="utf-8"), args.owner_id)
    result = publish_corpus(args.data_dir, rows) if args.apply else {"validated": len(rows), "changed": False}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
