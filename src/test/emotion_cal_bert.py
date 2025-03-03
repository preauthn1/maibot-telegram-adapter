from transformers import pipeline, AutoModelForSequenceClassification, AutoTokenizer

def setup_bert_analyzer():
    """
    设置中文BERT情感分析器
    """
    # 使用专门针对中文情感分析的模型
    model_name = "uer/roberta-base-finetuned-jd-binary-chinese"
    
    try:
        # 加载模型和分词器
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSequenceClassification.from_pretrained(model_name)
        
        # 创建情感分析pipeline
        analyzer = pipeline("sentiment-analysis", 
                          model=model, 
                          tokenizer=tokenizer)
        
        return analyzer
    except Exception as e:
        print(f"模型加载错误: {str(e)}")
        return None

def analyze_emotion_bert(text, analyzer):
    """
    使用BERT模型进行中文情感分析
    """
    try:
        if not analyzer:
            return None
            
        # 进行情感分析
        result = analyzer(text)[0]
        
        return {
            'label': result['label'],
            'score': result['score']
        }
    except Exception as e:
        print(f"分析过程中出现错误: {str(e)}")
        return None

def get_emotion_description_bert(result):
    """
    将BERT的情感分析结果转换为描述性文字
    """
    if not result:
        return "无法分析情感"
    
    label = "积极" if result['label'] == 'positive' else "消极"
    confidence = result['score']
    
    if confidence > 0.9:
        strength = "强烈"
    elif confidence > 0.7:
        strength = "明显"
    else:
        strength = "轻微"
    
    return f"{strength}{label}"

if __name__ == "__main__":
    # 初始化分析器
    analyzer = setup_bert_analyzer()
    
    # 测试样例
    test_text = "这个产品质量很好，使用起来非常方便，推荐购买！"
    result = analyze_emotion_bert(test_text, analyzer)
    
    print(f"测试文本: {test_text}")
    if result:
        print(f"情感倾向: {get_emotion_description_bert(result)}")
        print(f"置信度: {result['score']:.2f}") 