#!/usr/bin/env python3
"""回放 reply_decision_cases，评估低成本预判（非 pytest）。

关键指标：误静默率 = 我们当时实际回复了、但预判判 must_silence 的比例。
旁观/引用信息在脱敏回放里只能从文本 [回复<user_xxx>…] 与 @user_xxx 近似，
因此 bystander 的近似是保守的；真正上线判定使用实体级 ID。
"""

from collections import Counter
from pathlib import Path

import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins"))
from telegram_user_adapter.reply_prejudge import MUST_SILENCE, ReplyPrejudge  # noqa: E402

CASES = ROOT / "data/replay/reply_decision_cases.jsonl"
_REPLY_TAG = re.compile(r"^\[回复<(user_[0-9a-f]{6})>")
_AT = re.compile(r"@user_[0-9a-f]{6}")

pre = ReplyPrejudge()
stats = Counter()
reasons_on_reply = Counter()
reasons_on_silence = Counter()
examples = []
clock = 0.0
for line in CASES.read_text(encoding="utf-8").splitlines():
    case = json.loads(line)
    clock += 10.0
    # 用上下文中我们的出站喂同梗计数（与线上 note_outbound 对齐）。
    for item in case["context"][-1:]:
        if item["who"] == "self":
            pre.note_outbound(case["chat"], item["text"], now=clock)
    text = case["text"]
    reply_tag = _REPLY_TAG.match(text)
    # 回放无法知道被回复者是不是我们：若被标为 is_mention 则视为回复我们。
    replies_to_other = bool(reply_tag) and not case["is_mention"]
    mentions_other = bool(_AT.search(text)) and not case["is_mention"]
    result = pre.judge(
        chat_id=case["chat"],
        text=re.sub(r"^\[回复<[^>]*>：.*?\]，说：", "", text),
        is_mention=case["is_mention"],
        is_group=True,
        mentions_other=mentions_other,
        replies_to_other=replies_to_other,
        now=clock,
    )
    silenced = result.level == MUST_SILENCE
    stats[(case["label"], "silenced" if silenced else "passed")] += 1
    if silenced:
        (reasons_on_reply if case["label"] == "reply" else reasons_on_silence)[result.reason] += 1
        if case["label"] == "reply" and len(examples) < 12:
            examples.append((result.reason, text[:60]))

reply_total = stats[("reply", "silenced")] + stats[("reply", "passed")]
silence_total = stats[("silence", "silenced")] + stats[("silence", "passed")]
print("实际回复样本:", reply_total, " 被预判静默:", stats[("reply", "silenced")],
      f"误静默率={stats[('reply', 'silenced')] / max(1, reply_total):.2%}")
print("实际沉默样本:", silence_total, " 被预判静默:", stats[("silence", "silenced")],
      f"节省进入Host比例={stats[('silence', 'silenced')] / max(1, silence_total):.2%}")
print("误静默原因:", dict(reasons_on_reply))
print("正确静默原因:", dict(reasons_on_silence))
for reason, text in examples:
    print(" 误静默例:", reason, "|", text)
