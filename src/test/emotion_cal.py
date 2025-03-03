from textblob import TextBlob
import jieba
from translate import Translator

def analyze_emotion(text):
    """
    分析文本的情感,返回情感极性和主观性得分
    :param text: 输入文本
    :return: (情感极性, 主观性) 元组
    情感极性: -1(非常消极) 到 1(非常积极)
    主观性: 0(客观) 到 1(主观)
    """
    try:
        # 创建翻译器
        translator = Translator(to_lang="en", from_lang="zh")
        
        # 如果是中文文本,先翻译成英文
        # 因为TextBlob的情感分析主要基于英文
        translated_text = translator.translate(text)
        
        # 创建TextBlob对象
        blob = TextBlob(translated_text)
        
        # 获取情感极性和主观性
        polarity = blob.sentiment.polarity
        subjectivity = blob.sentiment.subjectivity
        
        return polarity, subjectivity
        
    except Exception as e:
        print(f"分析过程中出现错误: {str(e)}")
        return None, None

def get_emotion_description(polarity, subjectivity):
    """
    根据情感极性和主观性生成描述性文字
    """
    if polarity is None or subjectivity is None:
        return "无法分析情感"
        
    # 情感极性描述
    if polarity > 0.5:
        emotion = "非常积极"
    elif polarity > 0:
        emotion = "较为积极"
    elif polarity == 0:
        emotion = "中性"
    elif polarity > -0.5:
        emotion = "较为消极"
    else:
        emotion = "非常消极"
        
    # 主观性描述
    if subjectivity > 0.7:
        subj = "非常主观"
    elif subjectivity > 0.3:
        subj = "较为主观"
    else:
        subj = "较为客观"
        
    return f"情感倾向: {emotion}, 表达方式: {subj}"

if __name__ == "__main__":
    # 测试样例
    test_text = "今天天气真好,我感到非常开心！"
    polarity, subjectivity = analyze_emotion(test_text)
    print(f"测试文本: {test_text}")
    print(f"情感极性: {polarity:.2f}")
    print(f"主观性得分: {subjectivity:.2f}")
    print(get_emotion_description(polarity, subjectivity)) 