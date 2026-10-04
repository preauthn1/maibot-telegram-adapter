#!/usr/bin/env python3
"""离线评测 runner（升级计划 Phase 8.3，非 pytest）。

基于 data/replay/ 三套脱敏回放集，输出可对比的指标；加 ``--save NAME`` 把结果
存到 data/replay/eval_NAME.json，再用 ``--diff A B`` 比较两次变更前后差异。

覆盖：
- decision_cases：预判在"实际回复"上的误静默率、在"实际沉默"上的拦截率。
- bystander_cases：@ 别人的消息被当成对我们说的比例（预判未判 bystander）。
- style_cases：我方历史出站的客服腔/分析腔/AI 腔命中率与长度分布。
- outbound_integrity_cases：工具标记、命令、内部标签、管人话术在出站里的残留率
  （用当前硬闸门判定能拦下多少）。
- memory_scope_cases：需要人工标注的越界召回样本，当前回放集没有，显式报告为 0 条。

子命令 ``necessity``（agi_discussion §2.0 下一步2）：
  用 reply_decision_cases 回放 Host 侧 ``score_reply_necessity``（纯函数、无 LLM、无网络），
  输出沉默精度/沉默召回/多余发言率等指标，同样支持 ``--save`` / ``--diff``::

    eval_runner.py necessity [--frequency 1.0] [--save NAME]

  回放口径（近似，结论只用于版本间 --diff，不当绝对值）：
  - 按会话顺序模拟 pending 积压：门控放行（Planner 消费）或期间我方有出站后清零；
  - 频率阈值与 runtime 一致：max(1, ceil(1/f²))；空窗加成、聊天流状态分量（±25）不回放；
  - 存在感惩罚用回放集自带的前 6 条上下文近似 5 分钟窗口；
  - 标签是弱标签（120 秒内我方是否出站），且入站已经过适配器预判过滤，
    "放行"只表示进入 Planner，不等于真的会回复。
"""

from math import ceil
from pathlib import Path

import json
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
from telegram_user_adapter.anti_policing import is_group_policing  # noqa: E402
from telegram_user_adapter.reply_prejudge import MUST_SILENCE, ReplyPrejudge  # noqa: E402

from src.maisaka.reply_necessity import (  # noqa: E402
    REPLY_NECESSITY_TRIGGER_SCORE,
    ReplyNecessityInput,
    score_reply_necessity,
)

ROOT = Path(__file__).resolve().parents[1] / "data/replay"
_AT = re.compile(r"@user_[0-9a-f]{6}")
_SERVICE = re.compile(r"(?:希望对你有帮助|如果你还有|随时告诉我|作为一个|总结一下|综上|首先.{0,20}其次|以下是|建议你|您好|亲)")
_ANALYSIS = re.compile(r"(?:从.{1,8}角度|本质上|一方面.{0,30}另一方面|值得注意的是|客观来说)")
_TOOL_MARK = re.compile(r"(?:<\/?(?:tool|function|plugin_proactive_task)|\[(?:CQ|reply|picid):|tool_call|```)")
_COMMAND = re.compile(r"^\s*/[a-zA-Z]")


def load(name: str) -> list:
    path = ROOT / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def eval_decision(cases: list) -> dict:
    pre = ReplyPrejudge()
    reply_total = silence_total = false_silence = true_silence = 0
    by_total = by_miss = 0
    clock = 0.0
    for case in cases:
        clock += 10.0
        text = case["text"]
        mentions_other = bool(_AT.search(text)) and not case["is_mention"]
        result = pre.judge(
            chat_id=case["chat"],
            text=re.sub(r"^\[回复<[^>]*>：.*?\]，说：", "", text),
            is_mention=case["is_mention"],
            is_group=True,
            mentions_other=mentions_other,
            replies_to_other=False,
            now=clock,
        )
        silenced = result.level == MUST_SILENCE
        if case["label"] == "reply":
            reply_total += 1
            false_silence += silenced
        else:
            silence_total += 1
            true_silence += silenced
        if mentions_other:
            by_total += 1
            by_miss += not (silenced and result.reason == "bystander")
    return {
        "decision_reply_cases": reply_total,
        "decision_false_silence_rate": round(false_silence / max(1, reply_total), 4),
        "decision_silence_cases": silence_total,
        "decision_true_silence_rate": round(true_silence / max(1, silence_total), 4),
        "bystander_cases": by_total,
        "bystander_miss_rate": round(by_miss / max(1, by_total), 4),
    }


def eval_style(cases: list) -> dict:
    lengths = [case["length"] for case in cases if case["length"]]
    service = sum(bool(_SERVICE.search(case["text"])) for case in cases)
    analysis = sum(bool(_ANALYSIS.search(case["text"])) for case in cases)
    return {
        "style_cases": len(cases),
        "style_service_tone_rate": round(service / max(1, len(cases)), 4),
        "style_analysis_tone_rate": round(analysis / max(1, len(cases)), 4),
        "style_len_median": statistics.median(lengths) if lengths else 0,
        "style_len_p95": sorted(lengths)[int(len(lengths) * 0.95) - 1] if lengths else 0,
    }


def eval_outbound(cases: list) -> dict:
    tool = sum(bool(_TOOL_MARK.search(case["text"])) for case in cases)
    command = sum(bool(_COMMAND.search(case["text"])) for case in cases)
    policing_now = sum(case["current_guard"] == "block" for case in cases)
    incident = [case for case in cases if case["label_source"] == "incident_2026-10-03"]
    incident_blocked = sum(is_group_policing(case["text"]) for case in incident)
    return {
        "outbound_cases": len(cases),
        "outbound_tool_mark_rate": round(tool / max(1, len(cases)), 4),
        "outbound_command_rate": round(command / max(1, len(cases)), 4),
        "outbound_policing_guard_hits": policing_now,
        "incident_cases": len(incident),
        "incident_blocked_by_current_guard": incident_blocked,
    }


def eval_necessity(cases: list, frequency: float) -> dict:
    """按会话顺序回放 score_reply_necessity，统计门控判定与弱标签的一致性。"""

    effective_frequency = min(1.0, frequency)
    trigger_threshold = max(1, int(ceil(1.0 / (effective_frequency * effective_frequency))))
    pending_by_chat: dict = {}
    scores = []
    # 混淆矩阵：门控 trigger/wait × 弱标签 reply/silence
    trig_reply = trig_silence = wait_reply = wait_silence = 0
    mention_cases = mention_wait = 0
    for case in cases:
        context = case["context"]
        pending = pending_by_chat.setdefault(case["chat"], [])
        # 上一条入站之后我方有出站，说明期间 Planner 已运行，积压清零
        if context and context[-1]["who"] == "self":
            pending.clear()
        pending.append(case)
        recent_self = sum(item["who"] == "self" for item in context)
        result = score_reply_necessity(
            ReplyNecessityInput(
                texts=[item["text"] for item in pending],
                pending_count=len(pending),
                trigger_threshold=trigger_threshold,
                has_at=any(item["is_mention"] for item in pending),
                has_mention=any(item["is_mention"] for item in pending),
                is_group_chat=True,
                focus_active=False,
                recent_self_replies=recent_self,
                recent_window_messages=len(context) + 1,
                effective_frequency=frequency,
                idle_seconds=0.0,
                idle_reached_average=False,
            )
        )
        scores.append(result.score)
        triggered = result.score >= REPLY_NECESSITY_TRIGGER_SCORE
        if triggered:
            pending.clear()
        replied = case["label"] == "reply"
        trig_reply += triggered and replied
        trig_silence += triggered and not replied
        wait_reply += (not triggered) and replied
        wait_silence += (not triggered) and not replied
        if case["is_mention"]:
            mention_cases += 1
            mention_wait += not triggered
    total = len(cases)
    triggered_total = trig_reply + trig_silence
    waited_total = wait_reply + wait_silence
    sorted_scores = sorted(scores)
    return {
        "necessity_cases": total,
        "necessity_frequency": frequency,
        "necessity_trigger_threshold": trigger_threshold,
        "necessity_trigger_rate": round(triggered_total / max(1, total), 4),
        # 门控判沉默的样本里，弱标签也是沉默的比例
        "necessity_silence_precision": round(wait_silence / max(1, waited_total), 4),
        # 弱标签为沉默的样本里，门控也判沉默的比例
        "necessity_silence_recall": round(wait_silence / max(1, wait_silence + trig_silence), 4),
        # 门控放行的样本里，弱标签实际沉默的比例（多余发言率）
        "necessity_excess_speak_rate": round(trig_silence / max(1, triggered_total), 4),
        # 弱标签为回复的样本里，门控判沉默的比例（漏回率）
        "necessity_false_silence_rate": round(wait_reply / max(1, wait_reply + trig_reply), 4),
        "necessity_mention_cases": mention_cases,
        "necessity_mention_false_silence_rate": round(mention_wait / max(1, mention_cases), 4),
        "necessity_score_median": statistics.median(sorted_scores) if sorted_scores else 0,
        "necessity_score_p90": sorted_scores[int(len(sorted_scores) * 0.9) - 1] if sorted_scores else 0,
    }


def run() -> dict:
    metrics = {}
    metrics.update(eval_decision(load("reply_decision_cases")))
    metrics.update(eval_style(load("human_style_cases")))
    metrics.update(eval_outbound(load("outbound_safety_cases")))
    metrics["memory_scope_cases"] = 0  # 需人工标注越界召回样本，当前无数据
    return metrics


def main() -> None:
    if "--diff" in sys.argv:
        a, b = sys.argv[sys.argv.index("--diff") + 1 : sys.argv.index("--diff") + 3]
        ma = json.loads((ROOT / f"eval_{a}.json").read_text(encoding="utf-8"))
        mb = json.loads((ROOT / f"eval_{b}.json").read_text(encoding="utf-8"))
        for key in sorted(set(ma) | set(mb)):
            if ma.get(key) != mb.get(key):
                print(f"{key}: {ma.get(key)} -> {mb.get(key)}")
        return
    if len(sys.argv) > 1 and sys.argv[1] == "necessity":
        frequency = float(sys.argv[sys.argv.index("--frequency") + 1]) if "--frequency" in sys.argv else 1.0
        metrics = eval_necessity(load("reply_decision_cases"), frequency)
    else:
        metrics = run()
    for key, value in metrics.items():
        print(f"{key}: {value}")
    if "--save" in sys.argv:
        name = sys.argv[sys.argv.index("--save") + 1]
        target = ROOT / f"eval_{name}.json"
        target.write_text(json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
        target.chmod(0o600)
        print("saved:", target)


if __name__ == "__main__":
    main()
