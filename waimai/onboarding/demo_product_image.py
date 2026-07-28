# 新版新手体验：商品演示预设图（第 5、6 大步）

from __future__ import annotations

import base64

from django.core.files.uploadedfile import SimpleUploadedFile

# 最小可用 JPEG（1×1），供体验演示；须能被 Pillow 正常识别
_DEMO_JPEG_BYTES = base64.b64decode(
    b'/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof'
    b'Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwh'
    b'MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAAR'
    b'CAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAn/xAAUEAEAAAAAAAAAAAAAAAAA'
    b'AAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAA'
    b'IRAxEAPwCwAA//2Q=='
)


def demo_image_upload_file(*, index: int = 1) -> SimpleUploadedFile:
    """构造体验用预设图片文件"""
    return SimpleUploadedFile(
        f'experience_demo_{index}.jpg',
        _DEMO_JPEG_BYTES,
        content_type='image/jpeg',
    )


def attach_demo_preset_image(dish) -> tuple[dict | None, str | None]:
    """给演示商品附加一张预设图；返回 (payload, 错误文案)"""
    from waimai.product_image_helpers import upload_single_dish_image

    uploaded = demo_image_upload_file()
    return upload_single_dish_image(dish, uploaded)
