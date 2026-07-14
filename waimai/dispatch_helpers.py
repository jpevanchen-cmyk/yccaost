# 本店骑手派单逻辑（自动分配 + 手动指派）

from django.utils import timezone

from .delivery_helpers import calc_order_delivery_fee
from .models import BuyOrder, DeliveryOrder, User
from .staff_account_helpers import STAFF_WORK_ON_DUTY
from .order_helpers import subtotal_from_dish_items


def get_shop_riders(seller_id, *, active_only=True):
    """本店专属骑手列表；管理页可传 active_only=False 以显示已停用账号"""
    qs = User.objects.filter(role='rider', employer_seller_id=seller_id)
    if active_only:
        qs = qs.filter(is_active=True, staff_work_status=STAFF_WORK_ON_DUTY)
    return qs.order_by('date_joined')


def count_rider_active_orders(rider_username):
    """骑手当前未完成配送单数量"""
    return DeliveryOrder.objects.filter(
        rider_id=rider_username,
        delivery_status__in=['accepted', 'picked_up', 'in_transit'],
    ).count()


def auto_assign_rider(seller_id):
    """
    自动派单：在本店骑手中，优先派给手头未完成单最少的；
    相同则按注册先后轮询（先注册的优先）。
    """
    riders = list(get_shop_riders(seller_id).order_by('date_joined'))
    if not riders:
        return None
    riders.sort(key=lambda r: (count_rider_active_orders(r.username), r.date_joined))
    return riders[0].username


def validate_shop_rider(seller_id, rider_username):
    """确认骑手属于该店铺"""
    return get_shop_riders(seller_id).filter(username=rider_username).exists()


def auto_dispatch_enabled(seller_id: str) -> bool:
    """当前店铺是否开启自动派单"""
    from .operating_helpers import get_operating_settings

    settings = get_operating_settings(seller_id)
    return bool(getattr(settings, 'auto_dispatch_enabled', True))


def maybe_auto_dispatch_order(order):
    """若店铺开启自动派单，则自动尝试派给当前上班中的本店骑手"""
    if not order or order.fulfillment_type != 'delivery' or order.payment_status != 'paid':
        return None, None
    if hasattr(order, 'delivery_order'):
        return order.delivery_order, None
    if not auto_dispatch_enabled(order.seller_id):
        return None, None
    return dispatch_buy_order(order, rider_id=None)


def dispatch_buy_order(buy_order, rider_id=None):
    """
    为购买订单创建配送单并指派骑手。
    返回 (delivery_order, error_message)；成功时 error_message 为 None。
    """
    if buy_order.is_in_store():
        return None, '堂食或打包订单无需派骑手'

    if hasattr(buy_order, 'delivery_order'):
        return buy_order.delivery_order, None

    if buy_order.payment_status != 'paid':
        return None, '订单尚未支付，不能派单'
    if buy_order.order_status not in ('awaiting_prep', 'preparing', 'ready_pickup'):
        return None, '订单状态不允许派单'

    if not rider_id:
        rider_id = auto_assign_rider(buy_order.seller_id)
    if not rider_id:
        return None, '本店暂无可用骑手，请先在管理面板创建骑手账号'

    if not validate_shop_rider(buy_order.seller_id, rider_id):
        return None, '所选骑手不属于本店'

    subtotal = subtotal_from_dish_items(buy_order.dish_items)
    distance_km = float(buy_order.distance_km)
    delivery_fee = calc_order_delivery_fee(buy_order.seller_id, distance_km, subtotal)
    if delivery_fee is None:
        return None, '配送距离超出店铺设置'

    shop = buy_order.seller_id
    pickup = '店铺取餐点'
    try:
        from .models import ShopProfile
        profile = ShopProfile.objects.get(seller_id=shop)
        pickup = profile.address or pickup
    except ShopProfile.DoesNotExist:
        pass

    delivery = DeliveryOrder.objects.create(
        buy_order=buy_order,
        rider_id=rider_id,
        delivery_fee=delivery_fee,
        distance_km=buy_order.distance_km,
        pickup_address=pickup,
        delivery_address=buy_order.delivery_address,
        delivery_status='accepted',
        accepted_at=timezone.now(),
    )
    return delivery, None
