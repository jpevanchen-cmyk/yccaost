# 订单流程公共规则：避免服务员、后厨、提醒各写一套判断。

from django.db.models import Q

DISPATCHABLE_ORDER_STATUSES = ('awaiting_prep', 'preparing', 'ready_pickup')


def cash_order_can_prepare_before_payment(order) -> bool:
    """现金单是否允许先备货、后收款。"""
    return bool(
        order.payment_method == 'cash'
        and order.payment_status == 'pending_payment'
        and (
            order.fulfillment_type in ('dine_in', 'takeaway')
            or order.is_delivery_cod()
        )
    )


def cash_prepare_before_payment_q() -> Q:
    """与上面判断一致的数据库查询条件。"""
    return (
        Q(
            fulfillment_type__in=('dine_in', 'takeaway'),
            payment_method='cash',
            payment_status='pending_payment',
            order_status__in=(
                'awaiting_shop_confirm', 'awaiting_prep', 'preparing', 'ready_pickup',
            ),
        )
        | Q(
            fulfillment_type='delivery',
            payment_method='cash',
            payment_status='pending_payment',
            order_status__in=('awaiting_prep', 'preparing', 'ready_pickup'),
        )
    )


def order_can_start_preparing(order) -> bool:
    """订单能否开始备货：已付款，或允许先履约后收款。"""
    if order.order_status not in ('awaiting_shop_confirm', 'awaiting_prep'):
        return False
    return order.payment_status == 'paid' or cash_order_can_prepare_before_payment(order)


def order_can_dispatch(order) -> bool:
    """订单能否进入派单：已支付，或外卖货到付款等待配送员收款。"""
    if not order or order.fulfillment_type != 'delivery':
        return False
    if order.order_status not in DISPATCHABLE_ORDER_STATUSES:
        return False
    if hasattr(order, 'delivery_order'):
        return False
    return order.payment_status == 'paid' or order.is_cod_awaiting_collection()


def dispatchable_order_q() -> Q:
    """与 order_can_dispatch 一致的待派单池查询条件。"""
    return (
        Q(
            fulfillment_type='delivery',
            order_status__in=DISPATCHABLE_ORDER_STATUSES,
            delivery_order__isnull=True,
        )
        & (
            Q(payment_status='paid')
            | Q(payment_method='cash', payment_status='pending_payment')
        )
    )
