"""店铺后台与员工工作台共用的新订单提醒范围。"""

from django.db.models import Q

from .models import BuyOrder
from .order_workflow_rules import cash_prepare_before_payment_q


def shop_new_order_q() -> Q:
    """
    需要店家立即处理的新单：
    - 在线已付且待备货；
    - 或允许「先备货后收款」的现金/货到付款单（堂食、打包、外卖 COD）。
    纯待支付（支付页未选方式）不算新单。
    """
    return (
        Q(payment_status='paid', order_status='awaiting_prep')
        | cash_prepare_before_payment_q()
    )


def query_shop_new_orders(seller_id: str):
    """需要店家立即处理的新单。"""
    return BuyOrder.objects.filter(seller_id=seller_id).filter(shop_new_order_q())


def is_shop_new_order(order: BuyOrder) -> bool:
    """列表已取出后，按同一口径判断某一单是否仍算新单。"""
    if order.order_status == 'cancelled':
        return False
    if order.payment_status == 'paid' and order.order_status == 'awaiting_prep':
        return True
    if order.payment_status != 'pending_payment' or order.payment_method != 'cash':
        return False
    if order.order_status not in (
        'awaiting_shop_confirm', 'awaiting_prep', 'preparing', 'ready_pickup',
    ):
        return False
    if order.fulfillment_type in ('dine_in', 'takeaway'):
        return True
    return bool(order.is_delivery_cod())


def list_shop_new_order_links(seller_id: str, *, limit: int = 30) -> list[dict]:
    """新订单页顶直达链接用：一单一行，含展示号与详情网址。"""
    from django.urls import reverse

    rows = []
    for order in query_shop_new_orders(seller_id).order_by('-created_at')[:limit]:
        rows.append({
            'order_id': str(order.order_id),
            'display_no': order.get_display_order_no(),
            'url': reverse('order_detail', kwargs={'order_id': order.order_id}),
            'created_ts': int(order.created_at.timestamp() * 1000) if order.created_at else 0,
            'fulfillment': order.get_fulfillment_display_short(),
        })
    return rows


def maybe_notify_merchant_new_order(order: BuyOrder) -> None:
    """订单进入「商家应处理」范围时发邮件提醒（与响铃口径一致）。"""
    if not is_shop_new_order(order):
        return
    from .order_notify_helpers import notify_new_order

    notify_new_order(order)
    # 游客打包/外卖：同一时机发订单凭证（在线已付或已选现金/货到付款）
    from .guest_order_voucher_notify_helpers import schedule_guest_order_voucher_notify

    schedule_guest_order_voucher_notify(order)
