# 订单双方沟通：留言、未读、打开详情时记已读

from django.utils import timezone

from .models import BuyOrder, OrderMessage
from .shop_work_helpers import SHOP_STAFF_ROLES

MAX_MESSAGE_LEN = 300


def viewer_can_use_order_chat(user, order: BuyOrder) -> bool:
    """买家、店主、本店员工可留言；骑手只读看。"""
    if not user or not getattr(user, 'pk', None):
        return False
    if user.role == 'buyer':
        return order.buyer_id == user.username
    if user.role == 'seller':
        return order.seller_id == user.username
    if user.role in SHOP_STAFF_ROLES:
        return (user.employer_seller_id or '').strip() == order.seller_id
    return False


def viewer_is_shop_side(user) -> bool:
    return getattr(user, 'role', None) in ('seller',) + SHOP_STAFF_ROLES


def unread_count_for_viewer(order: BuyOrder, user) -> int:
    """当前查看方还有几条对方留言未读。"""
    if getattr(user, 'role', None) == 'buyer':
        since = order.buyer_msg_read_at
        qs = order.messages.filter(author_side='shop')
    elif viewer_is_shop_side(user):
        since = order.seller_msg_read_at
        qs = order.messages.filter(author_side='buyer')
    else:
        return 0
    if since:
        qs = qs.filter(created_at__gt=since)
    return qs.count()


def mark_order_messages_read(order: BuyOrder, user) -> None:
    """打开详情时记为已读。"""
    now = timezone.now()
    if getattr(user, 'role', None) == 'buyer' and order.buyer_id == user.username:
        BuyOrder.objects.filter(pk=order.pk).update(buyer_msg_read_at=now)
        order.buyer_msg_read_at = now
    elif viewer_is_shop_side(user) and viewer_can_use_order_chat(user, order):
        BuyOrder.objects.filter(pk=order.pk).update(seller_msg_read_at=now)
        order.seller_msg_read_at = now


def post_order_message(order: BuyOrder, user, body: str) -> tuple[bool, str]:
    """发送一条订单沟通留言。"""
    if not viewer_can_use_order_chat(user, order):
        return False, '您不能在此订单留言'
    text = (body or '').strip()
    if not text:
        return False, '请填写留言内容'
    if len(text) > MAX_MESSAGE_LEN:
        return False, f'留言请控制在 {MAX_MESSAGE_LEN} 字以内'

    side = 'buyer' if user.role == 'buyer' else 'shop'
    OrderMessage.objects.create(
        order=order,
        author_side=side,
        author_username=user.username,
        body=text,
    )
    # 自己发出的立即算已读，避免自己红点
    mark_order_messages_read(order, user)
    if side == 'shop':
        from .buyer_notify_helpers import schedule_buyer_order_message_notify

        schedule_buyer_order_message_notify(order, preview=text[:120])
    return True, '留言已发送'


def unread_map_for_orders(orders, *, side: str) -> dict:
    """
    批量算未读：side=buyer 看店家留言；side=shop 看买家留言。
    返回 {order_id: count}
    """
    order_list = list(orders)
    if not order_list:
        return {}
    ids = [o.order_id for o in order_list]
    by_id = {o.order_id: o for o in order_list}
    author = 'shop' if side == 'buyer' else 'buyer'
    rows = (
        OrderMessage.objects.filter(order_id__in=ids, author_side=author)
        .values_list('order_id', 'created_at')
    )
    counts = {oid: 0 for oid in ids}
    for oid, created_at in rows:
        order = by_id[oid]
        since = order.buyer_msg_read_at if side == 'buyer' else order.seller_msg_read_at
        if since is None or created_at > since:
            counts[oid] += 1
    return counts


def shop_unread_message_summary(seller_id: str, *, limit: int = 40) -> dict:
    """
    店家侧未读顾客沟通：总数 + 有未读的订单列表（供大标签红点与页顶直达）。
    返回 {'total': int, 'orders': [{'order': BuyOrder, 'count': int, ...}, ...]}
    """
    from django.db.models import F, Q
    from django.urls import reverse

    unread_qs = (
        OrderMessage.objects.filter(
            order__seller_id=seller_id,
            author_side='buyer',
        )
        .filter(
            Q(order__seller_msg_read_at__isnull=True)
            | Q(created_at__gt=F('order__seller_msg_read_at'))
        )
        .select_related('order')
        .order_by('-created_at')
    )
    total = unread_qs.count()
    # 按「最近一条未读」排订单，并累计每单未读条数
    grouped: dict = {}
    for msg in unread_qs[:300]:
        oid = msg.order_id
        if oid not in grouped:
            grouped[oid] = {'order': msg.order, 'count': 0}
        grouped[oid]['count'] += 1
    rows = list(grouped.values())[:limit]
    for row in rows:
        order = row['order']
        row['display_no'] = order.get_display_order_no()
        row['url'] = reverse('order_detail', kwargs={'order_id': order.order_id})
    return {'total': total, 'orders': rows}
