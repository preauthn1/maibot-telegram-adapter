from typing import Any, Dict, List, Tuple

from src.common.logger import get_logger
from src.common.database.database_model import Jargon
from src.plugin_system import BaseTool, ToolParamType

logger = get_logger("jargon_explanation")


class RecordJargonExplanationTool(BaseTool):
    """记录jargon解释工具
    
    检测聊天记录中是否有对某个词义的明确解释，如果有则记录到jargon表中
    """

    name: str = "record_explanation"
    description: str = (
        "当检测到有人明确解释了某个缩写，拼音缩写，中文缩写，英文缩写的含义时（例如：'xxx是yyy的意思'、'xxx指的是yyy'等)"
        "当某人明确纠正了对某个词汇的错误解释时（例如：'xxx不是yyy的意思'、'xxx不是指的是yyy'等)"
    )
    parameters: List[Tuple[str, ToolParamType, str, bool, None]] = [
        ("content", ToolParamType.STRING, "被解释的目标词汇（黑话/俚语/缩写），例如：yyds、内卷、社死等", True, None),
        ("translation", ToolParamType.STRING, "词汇的翻译或简称，例如：永远的神、社会性死亡等", True, None),
        ("meaning", ToolParamType.STRING, "词汇的详细含义说明", True, None),
    ]
    available_for_llm: bool = True

    async def execute(self, function_args: Dict[str, Any]) -> Dict[str, str]:
        """执行jargon解释检测和记录

        Args:
            function_args: 工具参数，包含content、translation、meaning

        Returns:
            dict: 工具执行结果
        """
        if not self.chat_id:
            return {"name": self.name, "content": "无法记录jargon解释：缺少chat_id"}

        try:
            # 从参数中获取信息
            content = str(function_args.get("content", "")).strip()
            translation = str(function_args.get("translation", "")).strip()
            meaning = str(function_args.get("meaning", "")).strip()
            
            if not content:
                return {"name": self.name, "content": "目标词汇不能为空"}
            
            if not translation and not meaning:
                return {"name": self.name, "content": "翻译和含义至少需要提供一个"}
                
            # 检查是否已存在相同的jargon
            query = Jargon.select().where(
                (Jargon.chat_id == self.chat_id) & 
                (Jargon.content == content)
            )
            
            if query.exists():
                # 已存在，更新translation和meaning（追加，用/分隔）
                obj = query.get()
                existing_translation = obj.translation or ""
                existing_meaning = obj.meaning or ""
                
                # 追加新内容
                if translation:
                    if existing_translation:
                        obj.translation = f"{existing_translation}/{translation}"
                    else:
                        obj.translation = translation
                
                if meaning:
                    if existing_meaning:
                        obj.meaning = f"{existing_meaning}/{meaning}"
                    else:
                        obj.meaning = meaning
                
                # 确保is_jargon为True
                obj.is_jargon = True
                obj.save()
                
                logger.info(f"更新jargon解释: {content}, translation={obj.translation}, meaning={obj.meaning}")
                # 优先使用meaning，如果没有则使用translation
                explanation = obj.meaning or obj.translation or ""
                return {"name": self.name, "content": f"你了解到 {content}的含义应该是 {explanation}"}
            else:
                # 新建记录
                Jargon.create(
                    content=content,
                    chat_id=self.chat_id,
                    translation=translation,
                    meaning=meaning,
                    is_jargon=True,
                    is_global=False,
                    count=0,
                )
                
                logger.info(f"记录新jargon解释: {content}, translation={translation}, meaning={meaning}")
                # 优先使用meaning，如果没有则使用translation
                explanation = meaning or translation or ""
                return {"name": self.name, "content": f"你了解到 {content}的含义应该是 {explanation}"}
                
        except Exception as exc:
            logger.error(f"记录jargon解释失败: {exc}", exc_info=True)
            return {"name": self.name, "content": f"记录jargon解释失败: {exc}"}


class LookupJargonMeaningTool(BaseTool):
    """查询jargon含义工具
    
    输入一个可能意义不明的词或缩写，查询数据库中是否已有匹配且带有含义或翻译的记录。
    命中则返回解释字符串（优先meaning，其次translation），未命中返回空字符串。
    """

    name: str = "lookup_jargon_meaning"
    description: str = (
        "查询是否存在已知的jargon解释（含meaning或translation），若存在返回解释，否则返回空字符串"
    )
    parameters: List[Tuple[str, ToolParamType, str, bool, None]] = [
        ("content", ToolParamType.STRING, "待查询的目标词汇（黑话/俚语/缩写）", True, None),
    ]
    available_for_llm: bool = True

    async def execute(self, function_args: Dict[str, Any]) -> Dict[str, str]:
        if not self.chat_id:
            # 和其它工具保持一致的返回结构
            return {"name": self.name, "content": ""}

        try:
            content = str(function_args.get("content", "")).strip()
            if not content:
                return {"name": self.name, "content": ""}

            # 优先在当前会话或global中查找该content，且需要meaning或translation非空
            # Peewee 条件：
            # (content == 输入) AND ((chat_id == 当前chat) OR is_global) AND ((meaning非空) OR (translation非空))
            candidates = (
                Jargon.select()
                .where(
                    (Jargon.content == content)
                    & ((Jargon.chat_id == self.chat_id) | Jargon.is_global)
                    & (
                        ((Jargon.meaning.is_null(False)) & (Jargon.meaning != ""))
                        | ((Jargon.translation.is_null(False)) & (Jargon.translation != ""))
                    )
                )
                .limit(1)
            )

            if candidates.exists():
                obj = candidates.get()
                translation = (obj.translation or "").strip()
                meaning = (obj.meaning or "").strip()
                formatted = f"“{content}可能为黑话或者网络简写，翻译为：{translation}，含义为：{meaning}”"
                return {"name": self.name, "content": formatted}

            # 未命中：允许退化为全库搜索（不限chat_id），以提升命中率
            fallback = (
                Jargon.select()
                .where(
                    (Jargon.content == content)
                    & (
                        ((Jargon.meaning.is_null(False)) & (Jargon.meaning != ""))
                        | ((Jargon.translation.is_null(False)) & (Jargon.translation != ""))
                    )
                )
                .limit(1)
            )
            if fallback.exists():
                obj = fallback.get()
                translation = (obj.translation or "").strip()
                meaning = (obj.meaning or "").strip()
                formatted = f"“{content}可能为黑话或者网络简写，翻译为：{translation}，含义为：{meaning}”"
                return {"name": self.name, "content": formatted}

            # 彻底未命中
            return {"name": self.name, "content": ""}
        except Exception as exc:
            logger.error(f"查询jargon解释失败: {exc}", exc_info=True)
            return {"name": self.name, "content": ""}

