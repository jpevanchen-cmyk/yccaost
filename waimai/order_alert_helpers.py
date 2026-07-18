"""店铺后台与员工工作台共用的新订单提醒范围。"""

from django.db.models import Q

from .models import BuyOrder


def shop_new_order_q() -> Q:
    """新单范围的共用查询条件。"""
    return (
        Q(order_status='awaiting_prep')
        | Q(
            order_status='awaiting_shop_confirm',
            fulfillment_type__in=('dine_in', 'takeaway'),
            payment_method='cash',
            payment_status='pending_payment',
        )
    )


def query_shop_new_orders(seller_id: str):
    """需要店家立即处理的新单：在线已付单，以及堂食/打包现场付单。"""
    return BuyOrder.objects.filter(seller_id=seller_id).filter(shop_new_order_q())


def is_shop_new_order(order: BuyOrder) -> bool:
    """列表已取出后，按同一口径判断某一单是否仍算新单。"""
    if order.order_status == 'awaiting_prep':
        return True
    return bool(
        order.order_status == 'awaiting_shop_confirm'
        and order.fulfillment_type in ('dine_in', 'takeaway')
        and order.payment_method == 'cash'
        and order.payment_status == 'pending_payment'
    )


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
