# 履约包：本店配送员派单逻辑（自动分配 + 手动指派）

from django.db import IntegrityError, transaction
from django.utils import timezone

from waimai.models import BuyOrder, DeliveryOrder, User
from waimai.order_helpers import subtotal_from_dish_items
from waimai.plugins.fulfillment.delivery_helpers import calc_order_delivery_fee
from waimai.staff_account_helpers import STAFF_WORK_ON_DUTY


def fulfillment_plugin_enabled(seller_id: str) -> bool:
    """本店是否启用履约配送插件。"""
    from waimai.plugins.fulfillment.ownership import fulfillment_plugin_enabled as _enabled

    return _enabled(seller_id)


def get_shop_riders(seller_id, *, active_only=True):
    """本店专属配送员列表；管理页可传 active_only=False 以显示已停用账号"""
    from waimai.staff_account_helpers import PERM_DINING_RIDER, staff_permission_query

    qs = User.objects.filter(
        staff_permission_query(PERM_DINING_RIDER),
        employer_seller_id=seller_id,
    )
    if active_only:
        qs = qs.filter(is_active=True, staff_work_status=STAFF_WORK_ON_DUTY)
    return qs.order_by('date_joined')


def count_rider_active_orders(rider_username):
    """配送员当前未完成配送单数量"""
    return DeliveryOrder.objects.filter(
        rider_id=rider_username,
        delivery_status__in=['accepted', 'picked_up', 'in_transit'],
    ).count()


def auto_assign_rider(seller_id):
    """
    自动派单：在本店配送员中，优先派给手头未完成单最少的；
    相同则按注册先后轮询（先注册的优先）。
    """
    riders = list(get_shop_riders(seller_id).order_by('date_joined'))
    if not riders:
        return None
    riders.sort(key=lambda r: (count_rider_active_orders(r.username), r.date_joined))
    return riders[0].username


def validate_shop_rider(seller_id, rider_username):
    """确认配送员属于该店铺"""
    return get_shop_riders(seller_id).filter(username=rider_username).exists()


def auto_dispatch_enabled(seller_id: str) -> bool:
    """当前店铺是否开启自动派单"""
    from waimai.operating_helpers import get_operating_settings

    settings = get_operating_settings(seller_id)
    return bool(getattr(settings, 'auto_dispatch_enabled', True))


def get_delivery_handoff_mode(seller_id: str) -> str:
    """外卖备好后由谁交接和手动派单；只在这里读取一次店铺设置。"""
    from waimai.operating_helpers import get_operating_settings

    settings = get_operating_settings(seller_id)
    mode = (getattr(settings, 'delivery_handoff_mode', '') or 'waiter').strip()
    return mode if mode in ('waiter', 'kitchen') else 'waiter'


def operator_can_manual_dispatch(operator, seller_id: str, work_view: str) -> bool:
    """店主始终可派；员工只有当前交接岗位可派。"""
    if getattr(operator, 'role', '') == 'seller':
        return True
    return work_view == get_delivery_handoff_mode(seller_id)


def query_pending_dispatch_orders(seller_id: str):
    """本店待派单池：能派、尚未生成配送单，最早下单排前面。"""
    from waimai.order_workflow_rules import dispatchable_order_q

    if not fulfillment_plugin_enabled(seller_id):
        return BuyOrder.objects.none()
    return (
        BuyOrder.objects.filter(dispatchable_order_q(), seller_id=seller_id)
        .order_by('created_at', 'order_id')
    )


def maybe_auto_dispatch_order(order):
    """若店铺开启自动派单且履约插件启用，则自动尝试派给当前上班中的本店配送员"""
    from waimai.order_workflow_rules import order_can_dispatch

    if not order_can_dispatch(order):
        return None, None
    if not fulfillment_plugin_enabled(order.seller_id):
        return None, '履约配送插件未启用，无法自动派单'
    if not auto_dispatch_enabled(order.seller_id):
        return None, None
    return dispatch_buy_order(order, rider_id=None)


def dispatch_buy_order(buy_order, rider_id=None):
    """
    为购买订单创建配送单并指派配送员。
    返回 (delivery_order, error_message)；成功时 error_message 为 None。
    """
    if hasattr(buy_order, 'delivery_order'):
        return buy_order.delivery_order, None

    if not fulfillment_plugin_enabled(buy_order.seller_id):
        return None, '履约配送插件未启用，无法派单'

    from waimai.order_workflow_rules import order_can_dispatch

    if not order_can_dispatch(buy_order):
        return None, '订单状态不允许派单'

    if not rider_id:
        rider_id = auto_assign_rider(buy_order.seller_id)
    if not rider_id:
        return None, '本店暂无上班中的可用配送员，订单已留在待派单池'

    if not validate_shop_rider(buy_order.seller_id, rider_id):
        return None, '所选配送员不属于本店'

    subtotal = subtotal_from_dish_items(buy_order.dish_items)
    distance_km = float(buy_order.distance_km)
    delivery_fee = calc_order_delivery_fee(buy_order.seller_id, distance_km, subtotal)
    if delivery_fee is None:
        return None, '配送距离超出店铺设置'

    shop = buy_order.seller_id
    pickup = '店铺取货点'
    try:
        from waimai.models import ShopProfile
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


def reassign_delivery_rider(buy_order, rider_id: str) -> tuple[bool, str]:
    """统一改派：只能在配送员尚未取货时，改给本店当前上班人员。"""
    rider_id = (rider_id or '').strip()
    if not rider_id:
        return False, '请选择配送员'
    if not validate_shop_rider(buy_order.seller_id, rider_id):
        return False, '只能改派给本店当前上班中的配送员'
    delivery = getattr(buy_order, 'delivery_order', None)
    if not delivery:
        return False, '订单尚未派单'
    if delivery.delivery_status != 'accepted':
        return False, '配送已开始，无法改派'
    if delivery.rider_id == rider_id:
        return True, f'仍由配送员 {rider_id} 配送'
    delivery.rider_id = rider_id
    delivery.save(update_fields=['rider_id', 'updated_at'])
    return True, f'已改派给配送员 {rider_id}'


def manual_dispatch_order(operator, work_view: str, buy_order, rider_id=None):
    """服务员/后厨共用的手动派单入口。"""
    if not operator_can_manual_dispatch(operator, buy_order.seller_id, work_view):
        return None, '当前店铺设置下，您没有手动派单权限'
    return dispatch_buy_order(buy_order, rider_id=(rider_id or '').strip() or None)


def try_dispatch_pending_for_rider(
    seller_id: str,
    rider_username: str,
    *,
    order_id=None,
) -> tuple[object | None, str | None]:
    """配送员主动接指定单；未指定时从待派池领取最早一单。"""
    rider_username = (rider_username or '').strip()
    if not validate_shop_rider(seller_id, rider_username):
        return None, '您当前不在本店可接单的配送员名单中'

    with transaction.atomic():
        pending = query_pending_dispatch_orders(seller_id).select_for_update()
        if order_id:
            order = pending.filter(order_id=order_id).first()
            if not order:
                return None, '这笔订单已被接走或当前不能派单'
        else:
            order = pending.first()
            if not order:
                return None, None
        try:
            return dispatch_buy_order(order, rider_id=rider_username)
        except IntegrityError:
            return None, '这笔订单刚被其他配送员接走，请刷新后重试'


def maybe_refill_dispatch_after_rider_available(rider):
    """配送员上班或送完一单后，空闲时从待派池自动补一单。"""
    from waimai.staff_account_helpers import PERM_DINING_RIDER, staff_has_permission

    seller_id = (getattr(rider, 'employer_seller_id', '') or '').strip()
    if not seller_id or not staff_has_permission(rider, PERM_DINING_RIDER):
        return None, None
    if not auto_dispatch_enabled(seller_id):
        return None, None
    if count_rider_active_orders(rider.username) > 0:
        return None, None
    return try_dispatch_pending_for_rider(seller_id, rider.username)
