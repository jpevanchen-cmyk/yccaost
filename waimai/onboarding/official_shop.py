# 官方演示店（新版 /experience/ 引导共用）

from __future__ import annotations

OFFICIAL_SHOP_NAME = '野草官方小店'

__all__ = [
    'OFFICIAL_SHOP_NAME',
    'get_official_shop_profile',
    'official_shop_ready',
]


def get_official_shop_profile():
    """取官方演示店；优先店名「野草官方小店」"""
    from waimai.models import ShopProfile

    qs = ShopProfile.objects.filter(is_official=True).order_by('shop_name')
    named = qs.filter(shop_name=OFFICIAL_SHOP_NAME).first()
    if named:
        return named
    return qs.first()


def official_shop_ready() -> bool:
    return get_official_shop_profile() is not None
