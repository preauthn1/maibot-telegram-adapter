import random

text = "我今天很开心 但是也很伤心 但是也很伤心，"
len_text = len(text)
print(f"len_text: {len_text}")
if len_text < 5:
    if random.random() < 0.01:
        print(f"直接按字符分割")
    else:
        print(f"直接按字符分割")
if len_text < 15:
    split_strength = 0.3
elif len_text < 35:
    split_strength = 0.7
else:
    split_strength = 0.9
#先移除换行符
print(f"split_strength: {split_strength}")

print(f"处理前的文本: {text}")

# 统一将英文逗号转换为中文逗号
text = text.replace(',', '，')
text = text.replace('\n', ' ')

print(f"处理前的文本: {text}")

text_no_1 = ''
for letter in text:
    print(f"当前字符: {letter}")
    if letter in ['!','！','?','？']:
        print(f"当前字符: {letter}, 随机数: {random.random()}")
        if random.random() < split_strength:
            letter = ''
    if letter in ['。','…']:
        print(f"当前字符: {letter}, 随机数: {random.random()}")
        if random.random() < 1 - split_strength:
            letter = ''
    text_no_1 += letter
    
# 对每个逗号和空格单独判断是否分割
sentences = [text_no_1]
new_sentences = []
for sentence in sentences:
    parts = sentence.split('，')
    current_sentence = parts[0]
    for part in parts[1:]:
        if random.random() < split_strength:
            new_sentences.append(current_sentence.strip())
            current_sentence = part
        else:
            current_sentence += '，' + part
    # 处理空格分割
    space_parts = current_sentence.split(' ')
    current_sentence = space_parts[0]
    for part in space_parts[1:]:
        if random.random() < split_strength:
            new_sentences.append(current_sentence.strip())
            current_sentence = part
        else:
            current_sentence += ' ' + part
    new_sentences.append(current_sentence.strip())
sentences = [s for s in new_sentences if s]  # 移除空字符串

print(f"分割后的句子: {sentences}")
sentences_done = []
for sentence in sentences:
    sentence = sentence.rstrip('，,')
    if random.random() < split_strength*0.5:
        sentence = sentence.replace('，', '').replace(',', '')
    elif random.random() < split_strength:
        sentence = sentence.replace('，', ' ').replace(',', ' ')
    sentences_done.append(sentence)
    
print(f"处理后的句子: {sentences_done}")
