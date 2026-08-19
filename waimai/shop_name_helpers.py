# 本机对外店名查重（进度 99）：开店与改名共用，不另拦官方名。

from __future__ import annotations

SHOP_NAME_TAKEN_MESSAGE = '这个店名已经有人用了，请换一个。'


def normalize_shop_name(name: str) -> str:
    """去掉首尾空格。空名字不算可用店名。"""
    return (name or '').strip()


def shop_name_is_taken(name: str, *, exclude_seller_id: str = '') -> bool:
    """同一台服务器上是否已有同样店名（不分大小写）。不处理库里已有的重名。"""
    from .models import ShopProfile

    n = normalize_shop_name(name)
    if not n:
        return False
    qs = ShopProfile.objects.filter(shop_name__iexact=n)
    sid = (exclude_seller_id or '').strip()
    if sid:
        qs = qs.exclude(seller_id=sid)
    return qs.exists()


def validate_new_shop_name(name: str, *, exclude_seller_id: str = '') -> str:
    """校验通过则返回整理后的店名；重名则抛出口语错误。"""
    from django.core.exceptions import ValidationError

    n = normalize_shop_name(name)
    if not n:
        raise ValidationError('请填写店铺名称。')
    if shop_name_is_taken(n, exclude_seller_id=exclude_seller_id):
        raise ValidationError(SHOP_NAME_TAKEN_MESSAGE)
    return n
