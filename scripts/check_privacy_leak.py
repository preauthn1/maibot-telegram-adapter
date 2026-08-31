"""推送前隐私扫描：检查已跟踪文件是否含真实身份信息。

覆盖：会话/账号 ID、用户名、群名、凭据、手机号。
"""

import re
import subprocess
import sys

PATTERNS = [
    (r"-100\d{10}", "疑似真实 Telegram 群 ID"),
    (r"\b89450244\d{2}\b", "账号 ID"),
    (r"graysoner", "账号用户名"),
    (r"某高风险小群|某低频群|某技术群|Komari|某小群|老王技术交流|某活跃群", "真实群名"),
    (r"(?:api_hash|session_string|token|secret|password)\W{0,4}[0-9a-f]{24,}", "疑似密钥"),
    (r"session_string\s*=\s*[\"'][A-Za-z0-9+/=]{20,}", "会话字符串"),
    (r"EULA_AGREE\s*=\s*[0-9a-f]{16,}", "EULA 令牌"),
    (r"api_hash\s*=\s*[\"'][0-9a-f]{20,}", "api_hash 明文"),
    (r"\bghp_[A-Za-z0-9]{20,}", "GitHub token"),
    (r"sk-[A-Za-z0-9]{20,}", "API key"),
]

# 明显的占位/示例值，不算泄漏。
# -1009xxxxxxxxx 是测试专用段，-100123456789x 是文档示例，
# -100<同一数字重复> 是手写的假 ID。
PLACEHOLDER = re.compile(
    r"-1009\d{9}|-1001234567890|-10011\d+|1000000001|1000000002|-100(\d)\1{9}"
)

files = subprocess.run(
    ["git", "ls-files"], capture_output=True, text=True, check=True
).stdout.splitlines()

# 只扫我们自己维护的代码。上游仓库自带的数据集与配置样例
# 会产生大量误报（字频小数被当手机号、示例 EULA 值等）。
OWN_PREFIXES = (
    "plugins/telegram_user_adapter/",
    "pytests/test_telegram_user",
    "pytests/test_scene_context",
    "pytests/test_context_merge",
    "pytests/test_idle_backoff",
    "src/maisaka/",
    "scripts/",
)
targets = [
    f
    for f in files
    if f.endswith((".py", ".md", ".json", ".toml")) and f.startswith(OWN_PREFIXES)
]

hits = []
for path in targets:
    try:
        with open(path, encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, 1):
                # 先剔除占位值，避免测试与文档里的示例 ID 触发误报。
                scrubbed = PLACEHOLDER.sub("", line)
                for pattern, label in PATTERNS:
                    if re.search(pattern, scrubbed):
                        hits.append((path, lineno, label, line.strip()[:80]))
    except (UnicodeDecodeError, FileNotFoundError):
        continue

print(f"扫描 {len(targets)} 个已跟踪文件\n")
if hits:
    print(f"⚠️  发现 {len(hits)} 处可疑内容：\n")
    for path, lineno, label, snippet in hits:
        print(f"  [{label}] {path}:{lineno}")
        print(f"      {snippet}")
    sys.exit(1)

print("✅ 未发现真实身份信息或凭据")
