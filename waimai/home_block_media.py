# 主页积木配图：本机/服务器上传 + 公开链接；每账号最多 100 张，单张 5MB

from __future__ import annotations

from django.core.exceptions import ValidationError

from .models import (
    MAX_HOME_BLOCK_IMAGE_BYTES,
    MAX_USER_UPLOADED_PHOTOS,
    UserUploadedPhoto,
    validate_home_block_image_size,
)

ALLOWED_IMAGE_EXT = frozenset({'png', 'jpg', 'jpeg', 'webp', 'gif'})


def count_user_uploaded_photos(user) -> int:
    if user is None or not getattr(user, 'pk', None):
        return 0
    return UserUploadedPhoto.objects.filter(owner=user).count()


def block_display_image_src(block) -> str:
    """前台用：优先本站上传图，否则公开链接。"""
    img = getattr(block, 'image', None)
    if img:
        try:
            # 无文件时 ImageFieldFile.name 为空，不能当已上传
            if getattr(img, 'name', None):
                url = img.url
                if url:
                    return url
        except (ValueError, AttributeError):
            pass
    return (getattr(block, 'image_url', None) or '').strip()


def apply_home_block_image_from_post(user, block, request, *, scope: str) -> str | None:
    """
    处理上传/清除配图。
    成功返回 None；失败返回给用户看的白话错误。
    scope: shop_home_block | server_home_block
    """
    clear = request.POST.get('clear_block_image') == '1'
    uploaded = request.FILES.get('block_image')

    if clear and not uploaded:
        _clear_block_image(user, block, scope)
        return None

    if not uploaded:
        return None

    # 扩展名与大小
    name = (getattr(uploaded, 'name', '') or '').lower()
    ext = name.rsplit('.', 1)[-1] if '.' in name else ''
    if ext not in ALLOWED_IMAGE_EXT:
        return '只支持 PNG、JPG、JPEG、WEBP、GIF 图片。'
    try:
        validate_home_block_image_size(uploaded)
    except ValidationError as exc:
        return '; '.join(exc.messages) if hasattr(exc, 'messages') else str(exc)

    existing = UserUploadedPhoto.objects.filter(
        owner=user, scope=scope, block_id=block.block_id,
    ).first()
    if existing is None and count_user_uploaded_photos(user) >= MAX_USER_UPLOADED_PHOTOS:
        return (
            f'本账号上传图片已达上限（{MAX_USER_UPLOADED_PHOTOS} 张）。'
            '请先清除不需要的积木配图后再上传。'
        )

    # 覆盖旧文件
    if block.image:
        block.image.delete(save=False)

    block.image = uploaded
    # 有本站图时不强制清空公开链接；前台优先用上传图
    block.save(update_fields=['image', 'updated_at'])

    if existing is None:
        UserUploadedPhoto.objects.create(
            owner=user,
            scope=scope,
            block_id=block.block_id,
        )
    else:
        existing.save(update_fields=['updated_at'])
    return None


def _clear_block_image(user, block, scope: str) -> None:
    if block.image:
        block.image.delete(save=False)
        block.image = None
        block.save(update_fields=['image', 'updated_at'])
    UserUploadedPhoto.objects.filter(
        owner=user, scope=scope, block_id=block.block_id,
    ).delete()


def release_block_photo_quota(user, block, scope: str) -> None:
    """删除积木时释放该块占用的上传名额，并删掉文件。"""
    if block.image:
        block.image.delete(save=False)
        block.image = None
    if user is not None and getattr(user, 'pk', None):
        UserUploadedPhoto.objects.filter(
            owner=user, scope=scope, block_id=block.block_id,
        ).delete()


def photo_quota_hint(user) -> dict:
    used = count_user_uploaded_photos(user)
    return {
        'photo_used': used,
        'photo_max': MAX_USER_UPLOADED_PHOTOS,
        'photo_remaining': max(0, MAX_USER_UPLOADED_PHOTOS - used),
        'photo_max_mb': MAX_HOME_BLOCK_IMAGE_BYTES // (1024 * 1024),
    }
