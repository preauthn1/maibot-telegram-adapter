"""jieba 自定义词典加载。

## 为什么需要

三方分词器实测（60072 条真实技术群语料，已剔除 bot 播报）：

    分词器        技术词切碎   中英边界   速度            额外依赖
    jieba          0/18       正确    20237 条/秒     无
    pyhanlp        1/18       正确     2437 条/秒     JVM + 637MB
    pkuseg-web     1/18       错误     3087 条/秒     17MB 模型
    pkuseg-def     2/18       错误     3251 条/秒     内置

jieba 综合最优（pkuseg 会把 `xhttp命/中`、`vless加reality` 粘错，
pyhanlp 慢 8.3 倍且要拖 JVM），因此保留 jieba。

但 jieba 词典里没有 2020 年后出现的代理协议词和圈内固定说法，
这些在语料里频次很高却被切碎：

    家宽    → 家 / 宽      （177 次）
    订阅器  → 订阅 / 器      （63 次）
    公网IP  → 公网 / IP     （27 次）

自定义词典只补这个缺口，不改变 jieba 其余行为。

## 用法

在任何调用 ``jieba.cut()`` 之前调用一次 :func:`ensure_user_dict_loaded`。
重复调用是安全的（内部有幂等标记）。
"""

from pathlib import Path

import jieba

from src.common.logger import get_logger

logger = get_logger("jieba_dict")

# 词典路径。用相对本模块的绝对路径，避免依赖进程工作目录；
# 放在 src/common/data/ 而非仓库根 data/（后者被 gitignore，
# 词典是代码依赖，必须随仓库分发）。
USER_DICT_PATH = Path(__file__).parent / "data" / "jieba_userdict.txt"

# 幂等标记。jieba.load_userdict 可重复调用但会重复读文件，
# 词频统计跑在消息入库路径上，没必要每次都读。
_loaded = False


def ensure_user_dict_loaded() -> bool:
    """确保自定义词典已加载到 jieba。

    Returns:
        bool: 词典已生效返回 ``True``。文件不存在时返回 ``False``
            并记录警告——这不是致命错误，jieba 仍可用内置词典工作，
            只是技术词会被切碎。
    """

    global _loaded
    if _loaded:
        return True

    if not USER_DICT_PATH.exists():
        logger.warning(f"jieba 自定义词典不存在，跳过加载: {USER_DICT_PATH}")
        return False

    jieba.load_userdict(str(USER_DICT_PATH))
    _loaded = True
    logger.info(f"已加载 jieba 自定义词典: {USER_DICT_PATH}")
    return True
