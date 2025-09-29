import json
import os
import asyncio
from src.common.database.database_model import GraphNodes
from src.common.logger import get_logger

logger = get_logger("migrate")

async def set_all_person_known():
    """
    将person_info库中所有记录的is_known字段设置为True
    在设置之前，先清理掉user_id或platform为空的记录
    """
    logger.info("开始设置所有person_info记录为已认识...")

    try:
        from src.common.database.database_model import PersonInfo

        # 获取所有PersonInfo记录
        all_persons = PersonInfo.select()
        total_count = all_persons.count()

        logger.info(f"找到 {total_count} 个人员记录")

        if total_count == 0:
            logger.info("没有找到任何人员记录")
            return {"total": 0, "deleted": 0, "updated": 0, "known_count": 0}

        # 删除user_id或platform为空的记录
        deleted_count = 0
        invalid_records = PersonInfo.select().where(
            (PersonInfo.user_id.is_null())
            | (PersonInfo.user_id == "")
            | (PersonInfo.platform.is_null())
            | (PersonInfo.platform == "")
        )

        # 记录要删除的记录信息
        for record in invalid_records:
            user_id_info = f"'{record.user_id}'" if record.user_id else "NULL"
            platform_info = f"'{record.platform}'" if record.platform else "NULL"
            person_name_info = f"'{record.person_name}'" if record.person_name else "无名称"
            logger.debug(
                f"删除无效记录: person_id={record.person_id}, user_id={user_id_info}, platform={platform_info}, person_name={person_name_info}"
            )

        # 执行删除操作
        deleted_count = (
            PersonInfo.delete()
            .where(
                (PersonInfo.user_id.is_null())
                | (PersonInfo.user_id == "")
                | (PersonInfo.platform.is_null())
                | (PersonInfo.platform == "")
            )
            .execute()
        )

        if deleted_count > 0:
            logger.info(f"删除了 {deleted_count} 个user_id或platform为空的记录")
        else:
            logger.info("没有发现user_id或platform为空的记录")

        # 重新获取剩余记录数量
        remaining_count = PersonInfo.select().count()
        logger.info(f"清理后剩余 {remaining_count} 个有效记录")

        if remaining_count == 0:
            logger.info("清理后没有剩余记录")
            return {"total": total_count, "deleted": deleted_count, "updated": 0, "known_count": 0}

        # 批量更新剩余记录的is_known字段为True
        updated_count = PersonInfo.update(is_known=True).execute()

        logger.info(f"成功更新 {updated_count} 个人员记录的is_known字段为True")

        # 验证更新结果
        known_count = PersonInfo.select().where(PersonInfo.is_known).count()

        result = {"total": total_count, "deleted": deleted_count, "updated": updated_count, "known_count": known_count}

        logger.info("=== person_info更新完成 ===")
        logger.info(f"原始记录数: {result['total']}")
        logger.info(f"删除记录数: {result['deleted']}")
        logger.info(f"更新记录数: {result['updated']}")
        logger.info(f"已认识记录数: {result['known_count']}")

        return result

    except Exception as e:
        logger.error(f"更新person_info过程中发生错误: {e}")
        raise


async def check_and_run_migrations():
    # 获取根目录
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    data_dir = os.path.join(project_root, "data")
    temp_dir = os.path.join(data_dir, "temp")
    done_file = os.path.join(temp_dir, "done.mem")

    # 检查done.mem是否存在
    if not os.path.exists(done_file):
        # 如果temp目录不存在则创建
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir, exist_ok=True)
        # 执行迁移函数
        # 依次执行两个异步函数
        await asyncio.sleep(3)
        await set_all_person_known()
        # 创建done.mem文件
        with open(done_file, "w", encoding="utf-8") as f:
            f.write("done")
