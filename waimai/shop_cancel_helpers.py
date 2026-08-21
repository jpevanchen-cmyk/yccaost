# 店铺注销第一刀（手册 A.2.3）
# 正式店：软关店（cancelled_at + 下架名录），档案保留；个人号不动。
# 体验店：按日清同样拆店（不套满 3 个月）。订单历史正式店不删。

from __future__ import annotations

from django.db import transaction

from .models import BuyOrder, CashRemittanceRequest, ShopProfile
from .operating_helpers import has_open_orders
from .time_helpers import now_local_wall

# 少收等未结清（与订单模型口径一致）
_UNSETTLED_SHORTFALL = ('buyer_pending', 'buyer_rejected', 'exception')


def get_seller_shop(user) -> ShopProfile | None:
    seller_id = (getattr(user, 'username', '') or '').strip()
    if not seller_id:
        return None
    return ShopProfile.objects.filter(seller_id=seller_id).first()


def shop_is_cancelled(shop: ShopProfile | None) -> bool:
    if shop is None:
        return False
    return bool(getattr(shop, 'cancelled_at', None))


def experience_shop_uses_teardown(shop: ShopProfile, user) -> bool:
    """体验机上的非官方体验店：注销时直接拆店（与日清同类）。"""
    from .experience_helpers import experience_site_enabled

    if not experience_site_enabled():
        return False
    if shop is None or shop.is_official:
        return False
    if not user or getattr(user, 'is_permanent', False):
        return False
    if not getattr(user, 'is_experience', False):
        return False
    return True


def seller_has_unsettled_matters(seller_id: str) -> bool:
    """少收待确认等未结清，或待确认的交款申请。"""
    sid = (seller_id or '').strip()
    if not sid:
        return False
    if BuyOrder.objects.filter(
        seller_id=sid,
        cash_shortfall_status__in=_UNSETTLED_SHORTFALL,
    ).exists():
        return True
    if CashRemittanceRequest.objects.filter(seller_id=sid, status='pending').exists():
        return True
    return False


def shop_cancel_block_reason(user, shop: ShopProfile | None = None) -> str:
    """不能办理店铺注销时返回人话；可以办理返回空串。"""
    from .account_helpers import user_has_seller_capability, user_is_staff_badge

    if user_is_staff_badge(user):
        return '工牌不能办理店铺注销，请用店主个人账户。'
    if not user_has_seller_capability(user):
        return '请用已开店的个人账户登录后再办理。'
    shop = shop or get_seller_shop(user)
    if shop is None:
        return '本账号下没有店铺资料，无需办理店铺注销。'
    if shop_is_cancelled(shop):
        return '本店已经注销过了。'
    seller_id = shop.seller_id
    if has_open_orders(seller_id):
        return '请先把进行中的订单全部处理完（完成或取消），再注销店铺。'
    if seller_has_unsettled_matters(seller_id):
        return '还有少收待确认、现金异常或待确认的交款申请，请先结清后再注销店铺。'
    return ''


def soft_cancel_shop(shop: ShopProfile) -> None:
    """正式店软注销：记下注销时间、退出名录。可安全重跑。"""
    if shop.cancelled_at is not None and not shop.is_listed:
        return
    shop.cancelled_at = shop.cancelled_at or now_local_wall()
    shop.is_listed = False
    shop.save(update_fields=['cancelled_at', 'is_listed'])


def shop_order_block_message(shop: ShopProfile | None) -> str:
    """客人侧：已注销店不能点餐时的人话。"""
    if shop_is_cancelled(shop):
        return '这家店已注销，暂时不能点餐。'
    return ''


def cancel_shop_for_owner(user) -> str:
    """
    执行店铺注销。须已通过 shop_cancel_block_reason。
    返回给人看的成功说明。
    """
    shop = get_seller_shop(user)
    reason = shop_cancel_block_reason(user, shop)
    if reason:
        raise ValueError(reason)
    assert shop is not None
    seller_id = shop.seller_id

    with transaction.atomic():
        if experience_shop_uses_teardown(shop, user):
            from .experience_helpers import teardown_experience_shops

            teardown_experience_shops([seller_id])
            return '体验店铺已拆掉（与日清同类）。个人登录号仍在。'

        soft_cancel_shop(shop)
        # 关掉接单，避免残留「营业中」
        try:
            from .operating_helpers import get_operating_settings

            ops = get_operating_settings(seller_id)
            ops.dine_channel_enabled = False
            ops.takeaway_channel_enabled = False
            ops.delivery_channel_enabled = False
            ops.guest_takeaway_enabled = False
            ops.guest_delivery_online_enabled = False
            ops.guest_delivery_cod_enabled = False
            ops.closed_for_today = True
            ops.pause_new_orders = True
            ops.save(update_fields=[
                'dine_channel_enabled', 'takeaway_channel_enabled',
                'delivery_channel_enabled', 'guest_takeaway_enabled',
                'guest_delivery_online_enabled', 'guest_delivery_cod_enabled',
                'closed_for_today', 'pause_new_orders',
            ])
        except Exception:
            pass

    return (
        '店铺已注销：客人不能再点餐，名录不再展示本店。'
        '店档案按规则保留约六个月；订单历史仍保留。个人登录号还在。'
    )
