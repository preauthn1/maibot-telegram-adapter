import hanlp

def analyze_emotion_hanlp(text):
    """
    使用HanLP进行中文情感分析
    """
    try:
        # 使用更基础的模型
        tokenizer = hanlp.load('PKU_NAME_MERGED_SIX_MONTHS_CONVSEG')
        
        # 分词
        words = tokenizer(text)
        
        # 简单的情感词典方法
        positive_words = {'好', '棒', '优秀', '喜欢', '开心', '快乐', '美味', '推荐', '优质', '满意'}
        negative_words = {'差', '糟', '烂', '讨厌', '失望', '难受', '恶心', '不满', '差劲', '垃圾'}
        
        # 计算情感得分
        score = 0
        for word in words:
            if word in positive_words:
                score += 1
            elif word in negative_words:
                score -= 1
                
        # 归一化得分
        if score > 0:
            return 1
        elif score < 0:
            return 0
        else:
            return 0.5
            
    except Exception as e:
        print(f"分析过程中出现错误: {str(e)}")
        return None

def get_emotion_description_hanlp(score):
    """
    将HanLP的情感分析结果转换为描述性文字
    """
    if score is None:
        return "无法分析情感"
    elif score == 1:
        return "积极"
    elif score == 0:
        return "消极"
    else:
        return "中性"

if __name__ == "__main__":
    # 测试样例
    test_texts = [
        "这家餐厅的服务态度很好，菜品也很美味！",
        "这个产品质量太差了，一点都不值这个价",
        "今天天气不错，但是工作很累"
    ]
    
    for test_text in test_texts:
        result = analyze_emotion_hanlp(test_text)
        print(f"\n测试文本: {test_text}")
        print(f"情感倾向: {get_emotion_description_hanlp(result)}") 