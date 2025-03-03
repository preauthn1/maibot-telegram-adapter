from snownlp import SnowNLP

def analyze_emotion_snownlp(text):
    """
    使用SnowNLP进行中文情感分析
    :param text: 输入文本
    :return: 情感得分(0-1之间，越接近1越积极)
    """
    try:
        s = SnowNLP(text)
        sentiment_score = s.sentiments
        
        # 获取文本的关键词
        keywords = s.keywords(3)
        
        return {
            'sentiment_score': sentiment_score,
            'keywords': keywords,
            'summary': s.summary(1)  # 生成文本摘要
        }
    except Exception as e:
        print(f"分析过程中出现错误: {str(e)}")
        return None

def get_emotion_description_snownlp(score):
    """
    将情感得分转换为描述性文字
    """
    if score is None:
        return "无法分析情感"
    
    if score > 0.8:
        return "非常积极"
    elif score > 0.6:
        return "较为积极"
    elif score > 0.4:
        return "中性偏积极"
    elif score > 0.2:
        return "中性偏消极"
    else:
        return "消极"

if __name__ == "__main__":
    # 测试样例
    test_text = "我们学校有免费的gpt4用"
    result = analyze_emotion_snownlp(test_text)
    
    if result:
        print(f"测试文本: {test_text}")
        print(f"情感得分: {result['sentiment_score']:.2f}")
        print(f"情感倾向: {get_emotion_description_snownlp(result['sentiment_score'])}")
        print(f"关键词: {', '.join(result['keywords'])}")
        print(f"文本摘要: {result['summary'][0]}") 