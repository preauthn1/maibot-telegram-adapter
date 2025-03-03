"""
错别字生成器 - 流程说明

整体替换逻辑：
1. 数据准备
   - 加载字频词典：使用jieba词典计算汉字使用频率
   - 创建拼音映射：建立拼音到汉字的映射关系
   - 加载词频信息：从jieba词典获取词语使用频率

2. 分词处理
   - 使用jieba将输入句子分词
   - 区分单字词和多字词
   - 保留标点符号和空格

3. 词语级别替换（针对多字词）
   - 触发条件：词长>1 且 随机概率<0.3
   - 替换流程：
     a. 获取词语拼音
     b. 生成所有可能的同音字组合
     c. 过滤条件：
        - 必须是jieba词典中的有效词
        - 词频必须达到原词频的10%以上
        - 综合评分(词频70%+字频30%)必须达到阈值
     d. 按综合评分排序，选择最合适的替换词

4. 字级别替换（针对单字词或未进行整词替换的多字词）
   - 单字替换概率：0.3
   - 多字词中的单字替换概率：0.3 * (0.7 ^ (词长-1))
   - 替换流程：
     a. 获取字的拼音
     b. 声调错误处理（20%概率）
     c. 获取同音字列表
     d. 过滤条件：
        - 字频必须达到最小阈值
        - 频率差异不能过大（指数衰减计算）
     e. 按频率排序选择替换字

5. 频率控制机制
   - 字频控制：使用归一化的字频（0-1000范围）
   - 词频控制：使用jieba词典中的词频
   - 频率差异计算：使用指数衰减函数
   - 最小频率阈值：确保替换字/词不会太生僻

6. 输出信息
   - 原文和错字版本的对照
   - 每个替换的详细信息（原字/词、替换后字/词、拼音、频率）
   - 替换类型说明（整词替换/声调错误/同音字替换）
   - 词语分析和完整拼音

注意事项：
1. 所有替换都必须使用有意义的词语
2. 替换词的使用频率不能过低
3. 多字词优先考虑整词替换
4. 考虑声调变化的情况
5. 保持标点符号和空格不变
"""

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
import time

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
    处理特殊情况：
    1. 轻声（如 'de5' 或 'le'）
    2. 非数字结尾的拼音
    """
    # 检查拼音是否为空或无效
    if not py or len(py) < 1:
        return py
        
    # 如果最后一个字符不是数字，说明可能是轻声或其他特殊情况
    if not py[-1].isdigit():
        # 为非数字结尾的拼音添加数字声调1
        return py + '1'
    
    base = py[:-1]  # 去掉声调
    tone = int(py[-1])  # 获取声调
    
    # 处理轻声（通常用5表示）或无效声调
    if tone not in [1, 2, 3, 4]:
        return base + str(random.choice([1, 2, 3, 4]))
    
    # 正常处理声调
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

def get_word_pinyin(word):
    """
    获取词语的拼音列表
    """
    return [py[0] for py in pinyin(word, style=Style.TONE3)]

def segment_sentence(sentence):
    """
    使用jieba分词，返回词语列表
    """
    return list(jieba.cut(sentence))

def get_word_homophones(word, pinyin_dict, char_frequency, min_freq=5):
    """
    获取整个词的同音词，只返回高频的有意义词语
    :param word: 输入词语
    :param pinyin_dict: 拼音字典
    :param char_frequency: 字频字典
    :param min_freq: 最小频率阈值
    :return: 同音词列表
    """
    if len(word) == 1:
        return []
        
    # 获取词的拼音
    word_pinyin = get_word_pinyin(word)
    word_pinyin_str = ''.join(word_pinyin)
    
    # 创建词语频率字典
    word_freq = defaultdict(float)
    
    # 遍历所有可能的同音字组合
    candidates = []
    for py in word_pinyin:
        chars = pinyin_dict.get(py, [])
        if not chars:
            return []
        candidates.append(chars)
    
    # 生成所有可能的组合
    import itertools
    all_combinations = itertools.product(*candidates)
    
    # 获取jieba词典和词频信息
    dict_path = os.path.join(os.path.dirname(jieba.__file__), 'dict.txt')
    valid_words = {}  # 改用字典存储词语及其频率
    with open(dict_path, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                word_text = parts[0]
                word_freq = float(parts[1])  # 获取词频
                valid_words[word_text] = word_freq
    
    # 获取原词的词频作为参考
    original_word_freq = valid_words.get(word, 0)
    min_word_freq = original_word_freq * 0.1  # 设置最小词频为原词频的10%
    
    # 过滤和计算频率
    homophones = []
    for combo in all_combinations:
        new_word = ''.join(combo)
        if new_word != word and new_word in valid_words:
            new_word_freq = valid_words[new_word]
            # 只保留词频达到阈值的词
            if new_word_freq >= min_word_freq:
                # 计算词的平均字频（考虑字频和词频）
                char_avg_freq = sum(char_frequency.get(c, 0) for c in new_word) / len(new_word)
                # 综合评分：结合词频和字频
                combined_score = (new_word_freq * 0.7 + char_avg_freq * 0.3)
                if combined_score >= min_freq:
                    homophones.append((new_word, combined_score))
    
    # 按综合分数排序并限制返回数量
    sorted_homophones = sorted(homophones, key=lambda x: x[1], reverse=True)
    return [word for word, _ in sorted_homophones[:5]]  # 限制返回前5个结果

def create_typo_sentence(sentence, pinyin_dict, char_frequency, error_rate=0.5, min_freq=5, tone_error_rate=0.2, word_replace_rate=0.3):
    """
    创建包含同音字错误的句子，支持词语级别和字级别的替换
    只使用高频的有意义词语进行替换
    """
    result = []
    typo_info = []
    
    # 分词
    words = segment_sentence(sentence)
    
    for word in words:
        # 如果是标点符号或空格，直接添加
        if all(not is_chinese_char(c) for c in word):
            result.append(word)
            continue
            
        # 获取词语的拼音
        word_pinyin = get_word_pinyin(word)
        
        # 尝试整词替换
        if len(word) > 1 and random.random() < word_replace_rate:
            word_homophones = get_word_homophones(word, pinyin_dict, char_frequency, min_freq)
            if word_homophones:
                typo_word = random.choice(word_homophones)
                # 计算词的平均频率
                orig_freq = sum(char_frequency.get(c, 0) for c in word) / len(word)
                typo_freq = sum(char_frequency.get(c, 0) for c in typo_word) / len(typo_word)
                
                # 添加到结果中
                result.append(typo_word)
                typo_info.append((word, typo_word, 
                                ' '.join(word_pinyin), 
                                ' '.join(get_word_pinyin(typo_word)), 
                                orig_freq, typo_freq))
                continue
        
        # 如果不进行整词替换，则进行单字替换
        if len(word) == 1:
            char = word
            py = word_pinyin[0]
            if random.random() < error_rate:
                similar_chars = get_similar_frequency_chars(char, py, pinyin_dict, char_frequency, 
                                                         min_freq=min_freq, tone_error_rate=tone_error_rate)
                if similar_chars:
                    typo_char = random.choice(similar_chars)
                    typo_freq = char_frequency.get(typo_char, 0)
                    orig_freq = char_frequency.get(char, 0)
                    replace_prob = calculate_replacement_probability(orig_freq, typo_freq)
                    if random.random() < replace_prob:
                        result.append(typo_char)
                        typo_py = pinyin(typo_char, style=Style.TONE3)[0][0]
                        typo_info.append((char, typo_char, py, typo_py, orig_freq, typo_freq))
                        continue
            result.append(char)
        else:
            # 处理多字词的单字替换
            word_result = []
            for i, (char, py) in enumerate(zip(word, word_pinyin)):
                # 词中的字替换概率降低
                word_error_rate = error_rate * (0.7 ** (len(word) - 1))
                
                if random.random() < word_error_rate:
                    similar_chars = get_similar_frequency_chars(char, py, pinyin_dict, char_frequency, 
                                                             min_freq=min_freq, tone_error_rate=tone_error_rate)
                    if similar_chars:
                        typo_char = random.choice(similar_chars)
                        typo_freq = char_frequency.get(typo_char, 0)
                        orig_freq = char_frequency.get(char, 0)
                        replace_prob = calculate_replacement_probability(orig_freq, typo_freq)
                        if random.random() < replace_prob:
                            word_result.append(typo_char)
                            typo_py = pinyin(typo_char, style=Style.TONE3)[0][0]
                            typo_info.append((char, typo_char, py, typo_py, orig_freq, typo_freq))
                            continue
                word_result.append(char)
            result.append(''.join(word_result))
    
    return ''.join(result), typo_info

def format_frequency(freq):
    """
    格式化频率显示
    """
    return f"{freq:.2f}"

def main():
    # 记录开始时间
    start_time = time.time()
    
    # 首先创建拼音字典和加载字频统计
    print("正在加载汉字数据库，请稍候...")
    pinyin_dict = create_pinyin_dict()
    char_frequency = load_or_create_char_frequency()
    
    # 获取用户输入
    sentence = input("请输入中文句子：")
    
    # 创建包含错别字的句子
    typo_sentence, typo_info = create_typo_sentence(sentence, pinyin_dict, char_frequency, 
                                                  error_rate=0.3, min_freq=5, 
                                                  tone_error_rate=0.2, word_replace_rate=0.3)
    
    # 打印结果
    print("\n原句：", sentence)
    print("错字版：", typo_sentence)
    
    if typo_info:
        print("\n错别字信息：")
        for orig, typo, orig_py, typo_py, orig_freq, typo_freq in typo_info:
            # 判断是否为词语替换
            is_word = ' ' in orig_py
            if is_word:
                error_type = "整词替换"
            else:
                tone_error = orig_py[:-1] == typo_py[:-1] and orig_py[-1] != typo_py[-1]
                error_type = "声调错误" if tone_error else "同音字替换"
            
            print(f"原文：{orig}({orig_py}) [频率：{format_frequency(orig_freq)}] -> "
                  f"替换：{typo}({typo_py}) [频率：{format_frequency(typo_freq)}] [{error_type}]")
    
    # 获取拼音结果
    result = get_pinyin(sentence)
    
    # 打印完整拼音
    print("\n完整拼音：")
    print(" ".join(py for _, py in result))
    
    # 打印词语分析
    print("\n词语分析：")
    words = segment_sentence(sentence)
    for word in words:
        if any(is_chinese_char(c) for c in word):
            word_pinyin = get_word_pinyin(word)
            print(f"词语：{word}")
            print(f"拼音：{' '.join(word_pinyin)}")
            print("---")
    
    # 计算并打印总耗时
    end_time = time.time()
    total_time = end_time - start_time
    print(f"\n总耗时：{total_time:.2f}秒")

if __name__ == "__main__":
    main()
