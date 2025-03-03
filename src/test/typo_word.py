from pypinyin import pinyin, Style
from collections import defaultdict
import json
import os
import unicodedata
import jieba
import jieba.posseg as pseg
from pathlib import Path
import random
import math

def load_or_create_char_frequency():
    """
    加载或创建汉字频率字典
    """
    cache_file = Path("char_frequency.json")
    
    # 如果缓存文件存在，直接加载
    if cache_file.exists():
        with open(cache_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    # 使用内置的词频文件
    char_freq = defaultdict(int)
    dict_path = os.path.join(os.path.dirname(jieba.__file__), 'dict.txt')
    
    # 读取jieba的词典文件
    with open(dict_path, 'r', encoding='utf-8') as f:
        for line in f:
            word, freq = line.strip().split()[:2]
            # 对词中的每个字进行频率累加
            for char in word:
                if is_chinese_char(char):
                    char_freq[char] += int(freq)
    
    # 归一化频率值
    max_freq = max(char_freq.values())
    normalized_freq = {char: freq/max_freq * 1000 for char, freq in char_freq.items()}
    
    # 保存到缓存文件
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(normalized_freq, f, ensure_ascii=False, indent=2)
    
    return normalized_freq

# 创建拼音到汉字的映射字典
def create_pinyin_dict():
    """
    创建拼音到汉字的映射字典
    """
    # 常用汉字范围
    chars = [chr(i) for i in range(0x4e00, 0x9fff)]
    pinyin_dict = defaultdict(list)
    
    # 为每个汉字建立拼音映射
    for char in chars:
        try:
            py = pinyin(char, style=Style.TONE3)[0][0]
            pinyin_dict[py].append(char)
        except Exception:
            continue
    
    return pinyin_dict

def is_chinese_char(char):
    """
    判断是否为汉字
    """
    try:
        return '\u4e00' <= char <= '\u9fff'
    except:
        return False

def get_pinyin(sentence):
    """
    将中文句子拆分成单个汉字并获取其拼音
    :param sentence: 输入的中文句子
    :return: 每个汉字及其拼音的列表
    """
    # 将句子拆分成单个字符
    characters = list(sentence)
    
    # 获取每个字符的拼音
    result = []
    for char in characters:
        # 跳过空格和非汉字字符
        if char.isspace() or not is_chinese_char(char):
            continue
        # 获取拼音（数字声调）
        py = pinyin(char, style=Style.TONE3)[0][0]
        result.append((char, py))
    
    return result

def get_homophone(char, py, pinyin_dict, char_frequency, min_freq=5):
    """
    获取同音字，按照使用频率排序
    """
    homophones = pinyin_dict[py]
    # 移除原字并过滤低频字
    if char in homophones:
        homophones.remove(char)
    
    # 过滤掉低频字
    homophones = [h for h in homophones if char_frequency.get(h, 0) >= min_freq]
    
    # 按照字频排序
    sorted_homophones = sorted(homophones, 
                             key=lambda x: char_frequency.get(x, 0), 
                             reverse=True)
    
    # 只返回前10个同音字，避免输出过多
    return sorted_homophones[:10]

def get_similar_tone_pinyin(py):
    """
    获取相似声调的拼音
    例如：'ni3' 可能返回 'ni2' 或 'ni4'
    """
    base = py[:-1]  # 去掉声调
    tone = int(py[-1])  # 获取声调
    possible_tones = [1, 2, 3, 4]
    possible_tones.remove(tone)  # 移除原声调
    new_tone = random.choice(possible_tones)  # 随机选择一个新声调
    return base + str(new_tone)

def calculate_replacement_probability(orig_freq, target_freq, max_freq_diff=200):
    """
    根据频率差计算替换概率
    频率差越大，概率越低
    :param orig_freq: 原字频率
    :param target_freq: 目标字频率
    :param max_freq_diff: 最大允许的频率差
    :return: 0-1之间的概率值
    """
    if target_freq > orig_freq:
        return 1.0  # 如果替换字频率更高，保持原有概率
    
    freq_diff = orig_freq - target_freq
    if freq_diff > max_freq_diff:
        return 0.0  # 频率差太大，不替换
    
    # 使用指数衰减函数计算概率
    # 频率差为0时概率为1，频率差为max_freq_diff时概率接近0
    return math.exp(-3 * freq_diff / max_freq_diff)

def get_similar_frequency_chars(char, py, pinyin_dict, char_frequency, num_candidates=5, min_freq=5, tone_error_rate=0.2):
    """
    获取与给定字频率相近的同音字，可能包含声调错误
    """
    homophones = []
    
    # 有20%的概率使用错误声调
    if random.random() < tone_error_rate:
        wrong_tone_py = get_similar_tone_pinyin(py)
        homophones.extend(pinyin_dict[wrong_tone_py])
    
    # 添加正确声调的同音字
    homophones.extend(pinyin_dict[py])
    
    if not homophones:
        return None
        
    # 获取原字的频率
    orig_freq = char_frequency.get(char, 0)
    
    # 计算所有同音字与原字的频率差，并过滤掉低频字
    freq_diff = [(h, char_frequency.get(h, 0)) 
                for h in homophones 
                if h != char and char_frequency.get(h, 0) >= min_freq]
    
    if not freq_diff:
        return None
    
    # 计算每个候选字的替换概率
    candidates_with_prob = []
    for h, freq in freq_diff:
        prob = calculate_replacement_probability(orig_freq, freq)
        if prob > 0:  # 只保留有效概率的候选字
            candidates_with_prob.append((h, prob))
    
    if not candidates_with_prob:
        return None
    
    # 根据概率排序
    candidates_with_prob.sort(key=lambda x: x[1], reverse=True)
    
    # 返回概率最高的几个字
    return [char for char, _ in candidates_with_prob[:num_candidates]]

def create_typo_sentence(sentence, pinyin_dict, char_frequency, error_rate=0.5, min_freq=5, tone_error_rate=0.2):
    """
    创建包含同音字错误的句子，保留原文标点符号
    """
    result = []
    typo_info = []
    
    # 获取每个字的拼音
    chars_with_pinyin = get_pinyin(sentence)
    
    # 创建原字到拼音的映射，用于跟踪已处理的字符
    processed_chars = {char: py for char, py in chars_with_pinyin}
    
    # 遍历原句中的每个字符
    char_index = 0
    for i, char in enumerate(sentence):
        if char.isspace():
            # 保留空格
            result.append(char)
        elif char in processed_chars:
            # 处理汉字
            py = processed_chars[char]
            # 基础错误率
            if random.random() < error_rate:
                # 获取频率相近的同音字（可能包含声调错误）
                similar_chars = get_similar_frequency_chars(char, py, pinyin_dict, char_frequency, 
                                                         min_freq=min_freq, tone_error_rate=tone_error_rate)
                if similar_chars:
                    # 随机选择一个替换字
                    typo_char = random.choice(similar_chars)
                    # 获取替换字的频率
                    typo_freq = char_frequency.get(typo_char, 0)
                    orig_freq = char_frequency.get(char, 0)
                    
                    # 计算实际替换概率
                    replace_prob = calculate_replacement_probability(orig_freq, typo_freq)
                    
                    # 根据频率差进行概率替换
                    if random.random() < replace_prob:
                        result.append(typo_char)
                        # 获取替换字的实际拼音
                        typo_py = pinyin(typo_char, style=Style.TONE3)[0][0]
                        typo_info.append((char, typo_char, py, typo_py, orig_freq, typo_freq))
                    else:
                        result.append(char)
                else:
                    result.append(char)
            else:
                result.append(char)
            char_index += 1
        else:
            # 保留非汉字字符（标点符号等）
            result.append(char)
    
    return ''.join(result), typo_info

def format_frequency(freq):
    """
    格式化频率显示
    """
    return f"{freq:.2f}"

def main():
    # 首先创建拼音字典和加载字频统计
    print("正在加载汉字数据库，请稍候...")
    pinyin_dict = create_pinyin_dict()
    char_frequency = load_or_create_char_frequency()
    
    # 获取用户输入
    sentence = input("请输入中文句子：")
    
    # 创建包含错别字的句子
    typo_sentence, typo_info = create_typo_sentence(sentence, pinyin_dict, char_frequency, 
                                                  min_freq=5, tone_error_rate=0.2)
    
    # 打印结果
    print("\n原句：", sentence)
    print("错字版：", typo_sentence)
    
    if typo_info:
        print("\n错别字信息：")
        for orig, typo, orig_py, typo_py, orig_freq, typo_freq in typo_info:
            tone_error = orig_py[:-1] == typo_py[:-1] and orig_py[-1] != typo_py[-1]
            error_type = "声调错误" if tone_error else "同音字替换"
            print(f"原字：{orig}({orig_py}) [频率：{format_frequency(orig_freq)}] -> "
                  f"错字：{typo}({typo_py}) [频率：{format_frequency(typo_freq)}] [{error_type}]")
    
    # 获取拼音结果
    result = get_pinyin(sentence)
    
    # 打印完整拼音
    print("\n完整拼音：")
    print(" ".join(py for _, py in result))
    
    # 打印所有可能的同音字
    print("\n每个字的所有同音字（按频率排序，仅显示频率>=5的字）：")
    for char, py in result:
        homophones = get_homophone(char, py, pinyin_dict, char_frequency, min_freq=5)
        char_freq = char_frequency.get(char, 0)
        print(f"{char}: {py} [频率：{format_frequency(char_freq)}]")
        if homophones:
            homophone_info = []
            for h in homophones:
                h_freq = char_frequency.get(h, 0)
                homophone_info.append(f"{h}[{format_frequency(h_freq)}]")
            print(f"同音字: {'，'.join(homophone_info)}")
        else:
            print("没有找到频率>=5的同音字")

if __name__ == "__main__":
    main()
