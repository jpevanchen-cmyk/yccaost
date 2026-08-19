# 生态个人账号主动注销（手册 A.2.3 第一刀）
# 不另存「已注销名单」；历史订单仍留在店里（买家栏只剩当时的登录名文字）。

from __future__ import annotations

from django.db import transaction

from .models import BuyOrder, ShopProfile

# 与「我的」里当前订单同一套：未完成、未取消
_OPEN_ORDER_STATUSES = ('completed', 'cancelled')


def buyer_has_open_orders(username: str) -> bool:
    name = (username or '').strip()
    if not name:
        return False
    return BuyOrder.objects.filter(buyer_id=name).exclude(
        order_status__in=_OPEN_ORDER_STATUSES,
    ).exists()


def experience_shop_may_teardown_on_cancel(user) -> bool:
    """体验机上、非官方体验店：注销时按日清同样拆店。"""
    from .experience_helpers import experience_site_enabled

    if not experience_site_enabled():
        return False
    if not user or getattr(user, 'is_permanent', False):
        return False
    if not getattr(user, 'is_experience', False):
        return False
    seller_id = (getattr(user, 'username', '') or '').strip()
    if not seller_id:
        return False
    shop = ShopProfile.objects.filter(seller_id=seller_id).first()
    if shop is None or shop.is_official:
        return False
    return True


def account_cancel_block_reason(user) -> str:
    """不能注销时返回人话；可以注销返回空串。"""
    from .account_helpers import user_has_buyer_capability, user_is_staff_badge
    from .account_helpers import user_has_seller_capability

    if user_is_staff_badge(user):
        return '工牌不能在这里注销，请用个人账户。'
    if not user_has_buyer_capability(user):
        return '请用个人账户登录后再注销。'
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_server_owner', False):
        return '这是本台服务器的管理者账号，不能在这里注销。'
    if buyer_has_open_orders(getattr(user, 'username', '')):
        return '请先把进行中的订单处理完，再注销账户。'
    if user_has_seller_capability(user) and not experience_shop_may_teardown_on_cancel(user):
        return '你已开通店铺。店铺注销尚未开通，有店的号暂时不能注销。'
    return ''


def cancel_eco_account(user) -> None:
    """拆体验店（若允许）后删除这个个人账户。须已通过 account_cancel_block_reason。"""
    from .experience_helpers import teardown_experience_shops

    reason = account_cancel_block_reason(user)
    if reason:
        raise ValueError(reason)
    seller_id = (getattr(user, 'username', '') or '').strip()
    with transaction.atomic():
        if experience_shop_may_teardown_on_cancel(user):
            teardown_experience_shops([seller_id])
        user.delete()
