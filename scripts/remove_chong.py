import difflib
import random


def ji_suan_xiang_si_du(wen_ben_yi: str, wen_ben_er: str) -> float:
    """
    计算两个文本字符串的相似度。

    参数:
        wen_ben_yi (str): 第一个文本字符串。
        wen_ben_er (str): 第二个文本字符串。

    返回:
        float: 两个文本的相似度比率 (0 到 1 之间)。
    """
    xu_lie_pi_pei_qi = difflib.SequenceMatcher(None, wen_ben_yi, wen_ben_er)
    # 获取相似度比率
    xiang_si_bi_lv = xu_lie_pi_pei_qi.ratio()
    return xiang_si_bi_lv


def ji_suan_ti_huan_gai_lv(xiang_si_du: float) -> float:
    """
    根据相似度计算替换的概率。
    规则：
    - 相似度 <= 0.4: 概率 = 0
    - 相似度 >= 0.9: 概率 = 1
    - 0.4 < 相似度 <= 0.6: 线性插值 (0.4, 0) 到 (0.6, 0.5)
    - 0.6 < 相似度 < 0.9: 线性插值 (0.6, 0.5) 到 (0.9, 1.0)
    """
    if xiang_si_du <= 0.4:
        return 0.0
    elif xiang_si_du >= 0.9:
        return 1.0
    elif 0.4 < xiang_si_du <= 0.6:
        # p = 2.5 * s - 1.0 (线性方程 y - 0 = (0.5-0)/(0.6-0.4) * (x - 0.4))
        gai_lv = 2.5 * xiang_si_du - 1.0
        return max(0.0, gai_lv)  # 确保概率不小于0
    elif 0.6 < xiang_si_du < 0.9:
        # p = (5/3) * s - 0.5 (线性方程 y - 0.5 = (1-0.5)/(0.9-0.6) * (x - 0.6))
        gai_lv = (5 / 3) * xiang_si_du - 0.5
        return min(1.0, max(0.0, gai_lv))  # 确保概率在 0 和 1 之间


# 获取用户输入
shu_ru_yi = "豆豆刚刚回复了我的问候 现在可以等待对方的回应 不需要再主动发言 目前情绪满足 不需要使用工具"

shu_ru_er = "豆豆刚刚回复了我的问候 现在可以等待对方的回应 不需要再主动发言 目前情绪满足 不需要使用工具 群主突然提到复活的事情 感觉有点莫名其妙 但情绪上还是满足的 暂时不需要回复"

# 计算相似度
xiang_si_du = ji_suan_xiang_si_du(shu_ru_yi, shu_ru_er)

# 计算替换概率
ti_huan_gai_lv = ji_suan_ti_huan_gai_lv(xiang_si_du)
print(f"文本相似度: {xiang_si_du:.2f}, 执行替换操作的概率: {ti_huan_gai_lv:.2f}")

# 根据概率决定是否执行替换
if random.random() < ti_huan_gai_lv:
    print(f"执行替换操作 (基于概率 {ti_huan_gai_lv:.2f})...")
    pi_pei_qi = difflib.SequenceMatcher(None, shu_ru_yi, shu_ru_er)
    qu_chong_hou_de_er = []
    last_match_end_in_b = 0
    # 获取匹配块 (i, j, n) 其中 a[i:i+n] == b[j:j+n]
    # 注意：get_matching_blocks 最后会有一个 (len(a), len(b), 0) 的虚拟块
    for _i, j, n in pi_pei_qi.get_matching_blocks():
        # 添加上一个匹配块结束到当前匹配块开始之间的非匹配部分 (来自文本二)
        if last_match_end_in_b < j:
            qu_chong_hou_de_er.append(shu_ru_er[last_match_end_in_b:j])
        # 更新下一个非匹配部分的起始位置
        last_match_end_in_b = j + n

    jie_guo = "".join(qu_chong_hou_de_er).strip()  # 去除首尾空白

    if jie_guo:
        # 定义词语列表
        yu_qi_ci_liebiao = ["嗯", "哦", "啊", "唉", "哈", "唔"]
        zhuan_zhe_liebiao = ["但是", "不过", "然而", "可是", "只是"]
        cheng_jie_liebiao = ["然后", "接着", "此外", "而且", "另外"]
        zhuan_jie_ci_liebiao = zhuan_zhe_liebiao + cheng_jie_liebiao

        # 根据概率决定是否添加词语
        qian_zhui_str = ""
        if random.random() < 0.3:  # 30% 概率添加语气词
            qian_zhui_str += random.choice(yu_qi_ci_liebiao)
        if random.random() < 0.7:  # 70% 概率添加转折/承接词
            qian_zhui_str += random.choice(zhuan_jie_ci_liebiao)

        # 组合最终结果
        if qian_zhui_str:
            zui_zhong_jie_guo = f"{qian_zhui_str}，{jie_guo}"
            print(f"移除重复部分并添加引导词后的文本二: {zui_zhong_jie_guo}")
        else:
            # 如果没有添加任何前缀词，直接输出去重结果
            print(f"移除重复部分后的文本二: {jie_guo}")
    else:
        print("移除重复部分后文本二为空。")
else:
    print(f"未执行替换操作 (基于概率 {ti_huan_gai_lv:.2f})。原始相似度为: {xiang_si_du:.2f}")
