from snownlp import SnowNLP

def demo_snownlp_features(text):
    """
    展示SnowNLP的主要功能
    :param text: 输入文本
    """
    print(f"\n=== SnowNLP功能演示 ===")
    print(f"输入文本: {text}")
    
    # 创建SnowNLP对象
    s = SnowNLP(text)
    
    # 1. 分词
    print(f"\n1. 分词结果:")
    print(f"   {' | '.join(s.words)}")
    
    # 2. 情感分析
    print(f"\n2. 情感分析:")
    sentiment = s.sentiments
    print(f"   情感得分: {sentiment:.2f}")
    print(f"   情感倾向: {'积极' if sentiment > 0.5 else '消极' if sentiment < 0.5 else '中性'}")
    
    # 3. 关键词提取
    print(f"\n3. 关键词提取:")
    print(f"   {', '.join(s.keywords(3))}")
    
    # 4. 词性标注
    print(f"\n4. 词性标注:")
    print(f"   {' '.join([f'{word}/{tag}' for word, tag in s.tags])}")
    
    # 5. 拼音转换
    print(f"\n5. 拼音:")
    print(f"   {' '.join(s.pinyin)}")
    
    # 6. 文本摘要
    if len(text) > 100:  # 只对较长文本生成摘要
        print(f"\n6. 文本摘要:")
        print(f"   {' '.join(s.summary(3))}")

if __name__ == "__main__":
    # 测试用例
    test_texts = [
        "这家新开的餐厅很不错，菜品种类丰富，味道可口，服务态度也很好，价格实惠，强烈推荐大家来尝试！",
        "这部电影剧情混乱，演技浮夸，特效粗糙，配乐难听，完全浪费了我的时间和票价。",
        """人工智能正在改变我们的生活方式。它能够帮助我们完成复杂的计算任务，
        提供个性化的服务推荐，优化交通路线，辅助医疗诊断。但同时我们也要警惕
        人工智能带来的问题，比如隐私安全、就业变化等。如何正确认识和利用人工智能，
        是我们每个人都需要思考的问题。"""
    ]
    
    for text in test_texts:
        demo_snownlp_features(text)
        print("\n" + "="*50) 