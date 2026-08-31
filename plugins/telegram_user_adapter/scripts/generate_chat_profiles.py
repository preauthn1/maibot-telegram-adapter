"""按真实聊天数据为每个白名单群生成画像卡（SKILL.md）。

画像不是拍脑袋写的：拉取各群近期消息，统计活跃人数、消息密度、
句长中位数、技术含量，据此推导约束参数。
"""

import asyncio
import sys
import tomllib
from collections import Counter
from datetime import timedelta, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

PLUGIN_DIR = Path("plugins/telegram_user_adapter")
OUT_ROOT = Path("data/plugins/preauthn1.telegram-user-adapter/chats")
CN = timezone(timedelta(hours=8))
# 自己的账号 ID，运行时从已登录会话读取，避免写死在版本库里。
ME = 0

TECH_WORDS = [
    "vless", "vmess", "trojan", "wireguard", "reality", "xray", "mihomo",
    "节点", "机场", "代理", "内核", "linux", "openwrt", "编译", "github",
    "gpl", "漏洞", "cve", "路由器", "vps", "服务器", "cloudflare", "dns",
    "docker", "nginx", "api", "脚本", "源码", "协议", "端口",
]


def build_card(chat_id, title, stats):
    """按统计结果生成画像卡内容。"""
    n = stats["count"]
    speakers = stats["speakers"]
    per_hour = stats["per_hour"]
    median_len = stats["median_len"]
    tech_pct = stats["tech_pct"]

    # 风险判定以「人少 + 安静」为主。
    #
    # 技术含量不能用通用词频衡量：这些群聊技术时说的是 MTE、JLS
    # 这类具体术语，通用词命中率最高才 11%，据此判定会全部漏判。
    # 真正决定风险的是社交结构——人少且安静的熟人圈，新面孔话多
    # 会被迅速聚焦；人多话杂的大群则会稀释掉发言。
    is_small = speakers <= 15
    is_quiet = per_hour < 10
    is_techy = tech_pct >= 8

    if is_small and is_quiet:
        risk = "高"
    elif is_small or is_quiet:
        risk = "中"
    else:
        risk = "低"

    # 句长上限：贴近该群中位数，留约 1.8 倍余量
    max_chars = 0 if risk == "低" else max(20, int(median_len * 1.8))
    # 参与率：群越小越安静，越要克制
    if risk == "高":
        ratio = 0.08
    elif risk == "中":
        ratio = 0.15
    else:
        ratio = 0.0
    # 发言间隔
    gap = 900 if risk == "高" else (300 if risk == "中" else 0)
    # 只有"人少 + 安静 + 有技术讨论"才封技术话题——
    # 这种群里说错一句就会被追问到底。
    block_tech = is_small and is_quiet and is_techy

    lines = ["---"]
    lines.append(f'title: "{title}"')
    if max_chars:
        lines.append(f"max_chars: {max_chars}")
    if ratio:
        lines.append(f"reply_ratio: {ratio}")
    if gap:
        lines.append(f"min_gap_seconds: {gap}")
    if block_tech:
        lines.append("block_tech: true")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"风险等级：**{risk}**")
    lines.append("")
    lines.append("## 实测画像")
    lines.append("")
    lines.append(f"- 样本 {n} 条，活跃发言者 {speakers} 人")
    lines.append(f"- 消息密度 {per_hour:.1f} 条/小时")
    lines.append(f"- 句长中位数 **{median_len} 字**")
    lines.append(f"- 技术含量 {tech_pct:.0f}%")
    if stats["top3_pct"]:
        lines.append(f"- 前 3 人占 {stats['top3_pct']:.0f}% 发言")
    lines.append("")
    lines.append("## 注意事项")
    lines.append("")
    if block_tech:
        lines.append("- **技术话题一概不接**：群里都是资深从业者，")
        lines.append("  说浅了露怯、说深了更可疑，闭嘴是最优解")
    if is_small:
        lines.append(f"- 人少（{speakers} 人），新面孔话多会被迅速聚焦")
    if is_quiet:
        lines.append(f"- 很安静（{per_hour:.1f} 条/小时），频繁发言非常突兀")
    if max_chars:
        lines.append(f"- 句子控制在 {max_chars} 字内，群内习惯短句")
    if not any([block_tech, is_small, is_quiet]):
        lines.append("- 人多话杂，发言会被稀释，按默认策略即可")
    lines.append("")
    lines.append("## 修改说明")
    lines.append("")
    lines.append("改完保存即生效，无需重启。frontmatter 字段：")
    lines.append("")
    lines.append("- `max_chars` 单条字数上限，0/省略=不限")
    lines.append("- `reply_ratio` 参与率上限，如 0.08 表示 8%")
    lines.append("- `min_gap_seconds` 两次发言最小间隔")
    lines.append("- `block_tech` 是否回避技术话题")
    lines.append("- `extra_keywords` 该群额外禁谈词，如 [\"内部\", \"报价\"]")
    lines.append("")
    return "\n".join(lines)


async def main():
    cfg = tomllib.loads((PLUGIN_DIR / "config.toml").read_text(encoding="utf-8"))
    acc = cfg["telegram_account"]
    groups = cfg["chat"]["group_list"]

    client = TelegramClient(StringSession(acc["session_string"]), acc["api_id"], acc["api_hash"])
    await client.connect()

    global ME
    me = await client.get_me()
    ME = me.id

    for gid in groups:
        try:
            ent = await client.get_entity(int(gid))
            title = getattr(ent, "title", gid)
        except Exception as exc:
            print(f"跳过 {gid}: {type(exc).__name__}")
            continue

        msgs = []
        try:
            async for m in client.iter_messages(int(gid), limit=600):
                if m.message and m.sender_id != ME:
                    msgs.append(m)
        except Exception as exc:
            print(f"跳过 {gid} ({title}): {type(exc).__name__}")
            continue

        if len(msgs) < 20:
            print(f"跳过 {gid} ({title}): 样本仅 {len(msgs)} 条")
            continue

        span_h = max((msgs[0].date - msgs[-1].date).total_seconds() / 3600, 1)
        spk = Counter(m.sender_id for m in msgs)
        active = sum(1 for v in spk.values() if v >= 3)
        lens = sorted(len(m.message) for m in msgs)
        tech = sum(1 for m in msgs if any(w in m.message.lower() for w in TECH_WORDS))
        top3 = sum(n for _, n in spk.most_common(3)) / len(msgs) * 100

        stats = {
            "count": len(msgs),
            "speakers": active or len(spk),
            "per_hour": len(msgs) / span_h,
            "median_len": lens[len(lens) // 2],
            "tech_pct": tech / len(msgs) * 100,
            "top3_pct": top3,
        }

        out_dir = OUT_ROOT / str(gid)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "SKILL.md").write_text(build_card(gid, title, stats), encoding="utf-8")

        risk = "高" if (stats["speakers"] <= 15 and stats["per_hour"] < 10) else "-"
        print(
            f'{title[:16]:<18} {stats["speakers"]:>3}人 '
            f'{stats["per_hour"]:>6.1f}条/h 中位{stats["median_len"]:>3}字 '
            f'技术{stats["tech_pct"]:>3.0f}% 风险{risk}'
        )

    await client.disconnect()


asyncio.run(main())
