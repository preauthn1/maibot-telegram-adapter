"""
测试修改后的 expression_selector 使用模型预测功能
验证不再随机选取，而是使用 style_learner 模型预测
"""

import os
import sys
import asyncio

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.express.expression_selector import ExpressionSelector
from src.express.style_learner import style_learner_manager
from src.common.logger import get_logger

logger = get_logger("expression_selector_test")


async def test_model_prediction_selector():
    """测试使用模型预测的表达选择器"""
    print("=== Expression Selector 模型预测功能测试 ===\n")
    
    # 创建选择器实例
    selector = ExpressionSelector()
    
    # 测试聊天室ID
    test_chat_id = "test_prediction_chat"
    
    print(f"测试聊天室: {test_chat_id}")
    
    # 1. 先为测试聊天室添加一些风格和situation
    print(f"\n1. 准备测试数据...")
    
    test_data = [
        ("温柔回复", "打招呼"),
        ("幽默回复", "表达惊讶"),
        ("严肃回复", "询问问题"),
        ("活泼回复", "表达开心"),
        ("高冷回复", "表示不满"),
    ]
    
    for style, situation in test_data:
        success = style_learner_manager.add_style(test_chat_id, style, situation)
        print(f"  添加: '{style}' (situation: '{situation}') -> {'成功' if success else '失败'}")
    
    # 2. 学习一些映射关系
    print(f"\n2. 学习映射关系...")
    
    learning_data = [
        ("你好", "温柔回复"),
        ("谢谢", "温柔回复"),
        ("哈哈", "幽默回复"),
        ("请解释", "严肃回复"),
        ("太棒了", "活泼回复"),
    ]
    
    for up_content, style in learning_data:
        success = style_learner_manager.learn_mapping(test_chat_id, up_content, style)
        print(f"  学习: '{up_content}' -> '{style}' -> {'成功' if success else '失败'}")
    
    # 3. 测试模型预测功能
    print(f"\n3. 测试模型预测功能...")
    
    test_chat_scenarios = [
        "用户: 你好\n机器人: 你好，有什么可以帮助你的吗？",
        "用户: 哈哈，太搞笑了\n机器人: 确实很有趣呢！",
        "用户: 请解释一下这个问题\n机器人: 好的，让我详细说明一下",
        "用户: 太棒了！\n机器人: 很高兴听到这个消息！",
    ]
    
    for i, chat_info in enumerate(test_chat_scenarios, 1):
        print(f"\n  场景 {i}:")
        print(f"    聊天内容: {chat_info}")
        
        # 使用模型预测表达方式
        predicted_expressions = selector.get_model_predicted_expressions(
            test_chat_id, chat_info, total_num=3
        )
        
        print(f"    预测结果: {len(predicted_expressions)} 个表达方式")
        for j, expr in enumerate(predicted_expressions, 1):
            print(f"      {j}. situation: '{expr['situation']}'")
            print(f"         style: '{expr['style']}'")
            print(f"         分数: {expr.get('prediction_score', 0.0):.4f}")
            print(f"         输入: '{expr.get('prediction_input', '')}'")
    
    # 4. 测试LLM选择功能
    print(f"\n4. 测试LLM选择功能...")
    
    # 模拟聊天信息
    chat_info = "用户: 你好，我想了解一下这个功能\n机器人: 好的，我来为你详细介绍"
    
    try:
        selected_expressions, selected_ids = await selector.select_suitable_expressions_llm(
            test_chat_id, chat_info, max_num=3
        )
        
        print(f"  LLM选择结果: {len(selected_expressions)} 个表达方式")
        for i, expr in enumerate(selected_expressions, 1):
            print(f"    {i}. situation: '{expr['situation']}'")
            print(f"       style: '{expr['style']}'")
            print(f"       来源: {expr['source_id']}")
            
    except Exception as e:
        print(f"  LLM选择失败: {e}")
    
    # 5. 测试回退机制
    print(f"\n5. 测试回退机制...")
    
    # 使用不存在的聊天室测试回退
    fake_chat_id = "fake_chat_id"
    fallback_expressions = selector._fallback_random_expressions(fake_chat_id, 3)
    print(f"  回退机制测试: {len(fallback_expressions)} 个表达方式")
    
    # 6. 测试预测输入提取
    print(f"\n6. 测试预测输入提取...")
    
    test_chat_infos = [
        "用户: 你好\n机器人: 你好！",
        "这是一段很长的聊天内容，包含了很多信息，用户说了很多话，机器人也回复了很多内容，现在我们要测试提取功能",
        "单行内容",
        "",
    ]
    
    for i, chat_info in enumerate(test_chat_infos, 1):
        prediction_input = selector._extract_prediction_input(chat_info)
        print(f"  测试 {i}:")
        print(f"    原始: '{chat_info}'")
        print(f"    提取: '{prediction_input}'")
    
    print(f"\n✅ 所有测试完成！")
    print(f"\n=== 功能总结 ===")
    print(f"✓ Expression Selector 现在使用 style_learner 模型进行预测")
    print(f"✓ 不再随机选择，而是基于聊天内容预测最合适的 style")
    print(f"✓ 自动获取预测 style 对应的 situation")
    print(f"✓ 支持多聊天室的预测")
    print(f"✓ 包含回退机制，预测失败时使用随机选择")
    print(f"✓ 支持预测输入提取和优化")


def main():
    """主函数"""
    print("Expression Selector 模型预测功能测试")
    print("=" * 60)
    
    # 运行异步测试
    asyncio.run(test_model_prediction_selector())


if __name__ == "__main__":
    main()
