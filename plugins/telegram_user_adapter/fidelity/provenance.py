# SPDX-License-Identifier: GPL-3.0-only
# Modified 2026-10-06; see PORT_NOTICES.md.
"""来源是非可信元数据，不覆盖参与者身份，也不改变频道过滤。"""
from typing import Any, Dict


def peer_label(peer: Any) -> str:
    if peer is None:
        return ""
    for kind in ("user", "channel", "chat"):
        value = getattr(peer, kind + "_id", None)
        if isinstance(value, int):
            return f"{kind}:{value}"
    return ""


def provenance(message: Any) -> Dict[str, Any]:
    result = {"sender_peer": peer_label(getattr(message, "from_id", None)),
              "channel_post": bool(getattr(message, "post", False))}
    result["sender_chat"] = result["sender_peer"].startswith(("channel:", "chat:"))
    # A channel identity may be an anonymous admin OR send-as-channel; don't guess which.
    signature = getattr(message, "post_author", None)
    if signature:
        result["unverified_signature"] = str(signature)[:256]
    forward = getattr(message, "fwd_from", None)
    if forward:
        result["forward"] = {
            "source_peer": peer_label(getattr(forward, "from_id", None)),
            "hidden_name": str(getattr(forward, "from_name", "") or "")[:256],
            "unverified_signature": str(getattr(forward, "post_author", "") or "")[:256],
            "channel_post_id": getattr(forward, "channel_post", None),
        }
    return result
