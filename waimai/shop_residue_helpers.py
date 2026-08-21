# 登录名与店侧残留：防止销号后同名「领走」旧店

from __future__ import annotations


def username_has_shop_residue(username: str) -> bool:
    """
    该登录名下是否还留着店铺资料或店侧设置（含软注销保留期）。
    有残留则：不能销个人号；也不能再注册同名领走旧店。
    """
    name = (username or '').strip()
    if not name:
        return False
    from .models import (
        MenuProfile,
        ShopDeliverySettings,
        ShopHomePage,
        ShopOperatingSettings,
        ShopPaymentSettings,
        ShopProfile,
    )

    if ShopProfile.objects.filter(seller_id=name).exists():
        return True
    if ShopDeliverySettings.objects.filter(seller_id=name).exists():
        return True
    if ShopPaymentSettings.objects.filter(seller_id=name).exists():
        return True
    if ShopOperatingSettings.objects.filter(seller_id=name).exists():
        return True
    if ShopHomePage.objects.filter(seller_id=name).exists():
        return True
    if MenuProfile.objects.filter(seller_id=name).exists():
        return True
    return False


def shop_residue_blocks_account_cancel_message() -> str:
    return (
        '本账号下的店铺资料尚未彻底清理干净（含已关店但保留期内的档案）。'
        '请等店铺侧清理完成后再注销个人账户，以免同名账号领走旧店数据。'
    )


def shop_residue_blocks_register_message() -> str:
    return (
        '这个登录名暂不可用：系统里还留有同名的店铺资料或店侧设置。'
        '请换一个名字，或等该店彻底清理后再试。'
    )
