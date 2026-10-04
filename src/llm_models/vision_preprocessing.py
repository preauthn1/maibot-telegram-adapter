"""出站视觉图片预处理；不修改历史消息或磁盘原图。"""
from dataclasses import replace
from io import BytesIO
from typing import List

import base64
import warnings

from PIL import Image, ImageOps

from src.llm_models.payload_content.context_item import (
    AssistantMessageItem,
    ContextImagePart,
    ContextItem,
    SystemMessageItem,
    UserMessageItem,
)

MAX_VISION_IMAGE_BYTES = 1024 * 1024
MAX_VISION_IMAGE_SIDE = 1536


def prepare_vision_image(
    part: ContextImagePart,
    *,
    max_bytes: int = MAX_VISION_IMAGE_BYTES,
    max_side: int = MAX_VISION_IMAGE_SIDE,
) -> ContextImagePart:
    """将单张图片约束到原始字节和长边上限，并同步声明格式。"""
    if max_bytes <= 0 or max_side <= 0:
        raise ValueError("视觉图片大小和边长上限必须大于0")
    try:
        raw = base64.b64decode(part.image_base64, validate=True)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                actual_format = (image.format or "").lower()
                if actual_format not in {"jpeg", "png", "webp", "gif"}:
                    raise ValueError(f"不支持的格式: {actual_format}")
                if getattr(image, "is_animated", False):
                    raise ValueError("不支持直接发送动图，请先提取静态帧")
                image.load()  # 小图同样校验，损坏数据不能绕过预处理。
                if (
                    actual_format in {"jpeg", "png", "webp"}
                    and len(raw) <= max_bytes
                    and max(image.size) <= max_side
                    and image.getexif().get(274, 1) == 1
                ):
                    if actual_format == part.normalized_image_format:
                        return part
                    return replace(part, image_format=actual_format)
                normalized = ImageOps.exif_transpose(image)
                if "A" in normalized.getbands() or "transparency" in normalized.info:
                    # JPEG 不支持透明度，先合成白底，避免透明区域变黑。
                    rgba = normalized.convert("RGBA")
                    working = Image.new("RGB", rgba.size, "white")
                    working.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    working = normalized.convert("RGB")
        working.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        # 优先保留尺寸，逐步降低质量；仍超限则按原比例缩小后重试。
        for _ in range(16):
            for quality in (85, 75, 65, 55):
                output = BytesIO()
                working.save(output, format="JPEG", quality=quality, optimize=True)
                if output.tell() <= max_bytes:
                    return ContextImagePart(
                        image_format="jpeg", image_base64=base64.b64encode(output.getvalue()).decode("ascii")
                    )
            scale = min(0.9, (max_bytes / output.tell()) ** 0.5 * 0.95)
            size = (max(1, int(working.width * scale)), max(1, int(working.height * scale)))
            if size == working.size:
                break
            working = working.resize(size, Image.Resampling.LANCZOS)
    except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError(f"视觉图片预处理失败: {exc}") from exc
    raise ValueError("视觉图片无法压缩到指定大小")


def prepare_vision_messages(
    items: List[ContextItem],
    *,
    max_bytes: int = MAX_VISION_IMAGE_BYTES,
    max_side: int = MAX_VISION_IMAGE_SIDE,
) -> List[ContextItem]:
    """复制变化的消息，清除该消息的旧 replay，保持其它上下文不变。"""
    prepared = []
    for item in items:
        if not isinstance(item, (SystemMessageItem, UserMessageItem, AssistantMessageItem)):
            prepared.append(item)
            continue
        parts = tuple(
            prepare_vision_image(part, max_bytes=max_bytes, max_side=max_side)
            if isinstance(part, ContextImagePart) else part
            for part in item.parts
        )
        if parts == item.parts:
            prepared.append(item)
        elif isinstance(item, AssistantMessageItem):
            prepared.append(replace(item, parts=parts, replay=None))
        else:
            prepared.append(replace(item, parts=parts))
    return prepared
