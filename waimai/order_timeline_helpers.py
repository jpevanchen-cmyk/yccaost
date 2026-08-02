# 订单历程与时间线（进度 83 · 主状态机只读分支）
# 事件发生时写入 OrderTimelineEvent；展示统一走 build_order_timeline(viewer=…)。

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from django.utils import timezone

if TYPE_CHECKING:
    from .models import BuyOrder

# 历程事件代码（与 82 事件表对齐并扩展展示用）
TL_ORDER_CREATED = 'order_created'
TL_PAYMENT_RECEIVED = 'payment_received'
TL_PREP_STARTED = 'prep_started'
TL_READY = 'ready_for_handoff'
TL_GOODS_DELIVERED = 'goods_delivered'
TL_DELIVERY_ACCEPTED = 'delivery_accepted'
TL_DELIVERY_PICKED_UP = 'delivery_picked_up'
TL_DELIVERY_STARTED = 'delivery_started'
TL_DELIVERY_COMPLETED = 'delivery_completed'
TL_ORDER_COMPLETED = 'order_completed'
TL_ORDER_CANCELLED = 'order_cancelled'

VIEWER_BUYER = 'buyer'
VIEWER_SELLER = 'seller'
VIEWER_STAFF = 'staff'
VIEWER_WORK = 'work'
VIEWER_RIDER = 'rider'

# 各端可见事件（staff/work/seller 看全部业务节点）
_BUYER_CODES = frozenset({
    TL_ORDER_CREATED,
    TL_PAYMENT_RECEIVED,
    TL_READY,
    TL_DELIVERY_ACCEPTED,
    TL_DELIVERY_PICKED_UP,
    TL_DELIVERY_STARTED,
    TL_DELIVERY_COMPLETED,
    TL_ORDER_COMPLETED,
    TL_ORDER_CANCELLED,
})
_RIDER_CODES = frozenset({
    TL_DELIVERY_ACCEPTED,
    TL_DELIVERY_PICKED_UP,
    TL_DELIVERY_STARTED,
    TL_DELIVERY_COMPLETED,
    TL_ORDER_CANCELLED,
})
_STAFF_CODES = frozenset({
    TL_ORDER_CREATED,
    TL_PAYMENT_RECEIVED,
    TL_PREP_STARTED,
    TL_READY,
    TL_GOODS_DELIVERED,
    TL_DELIVERY_ACCEPTED,
    TL_DELIVERY_PICKED_UP,
    TL_DELIVERY_STARTED,
    TL_DELIVERY_COMPLETED,
    TL_ORDER_COMPLETED,
    TL_ORDER_CANCELLED,
})

# 仍处备制阶段才展示「预计出餐/取餐」
_ESTIMATED_READY_STATUSES = frozenset({
    'created',
    'awaiting_payment',
    'awaiting_shop_confirm',
    'awaiting_prep',
    'preparing',
})


def _timeline_sort_key(row: tuple[str, object]):
    """按发生时间排序；无时间的排最后。"""
    _lbl, dt = row
    if dt is None:
        return (1, datetime.max.replace(tzinfo=timezone.utc), _lbl)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return (0, dt, _lbl)


def _estimated_ready_label(order: BuyOrder) -> str:
    if order.is_basic_order():
        return '预计完成'
    if order.is_dine_in():
        return '预计出餐'
    if order.is_takeaway():
        return '预计可取餐'
    if order.fulfillment_type == 'delivery':
        return '预计出餐'
    return '预计时间'


def _should_show_estimated_ready(order: BuyOrder) -> bool:
    if not order.estimated_ready_at:
        return False
    if order.order_status in ('completed', 'cancelled'):
        return False
    return order.order_status in _ESTIMATED_READY_STATUSES


def _should_show_estimated_delivery(order: BuyOrder, delivery) -> bool:
    if not delivery or not delivery.estimated_delivery_time:
        return False
    if order.order_status in ('completed', 'cancelled'):
        return False
    if delivery.delivery_status in ('completed', 'cancelled'):
        return False
    return True


def _viewer_codes(viewer: str) -> frozenset[str] | None:
    """None 表示不过滤（内部调试）。"""
    v = (viewer or VIEWER_BUYER).strip().lower()
    if v in (VIEWER_SELLER, VIEWER_STAFF, VIEWER_WORK):
        return _STAFF_CODES
    if v == VIEWER_RIDER:
        return _RIDER_CODES
    return _BUYER_CODES


def record_timeline_event(
    order: BuyOrder,
    event_code: str,
    label: str,
    *,
    occurred_at=None,
    save_order_fields: list[str] | None = None,
    once: bool = False,
) -> None:
    """写入一条历程；可选同步更新订单/配送时间戳字段。once=True 时同码不重复写入。"""
    from .models import OrderTimelineEvent

    if once and order.timeline_events.filter(event_code=event_code).exists():
        return
    when = occurred_at or timezone.now()
    OrderTimelineEvent.objects.create(
        order=order,
        event_code=event_code,
        label=label,
        occurred_at=when,
    )
    if save_order_fields:
        order.save(update_fields=list(dict.fromkeys([*save_order_fields, 'updated_at'])))


def record_order_created(order: BuyOrder) -> None:
    if order.timeline_events.filter(event_code=TL_ORDER_CREATED).exists():
        return
    record_timeline_event(order, TL_ORDER_CREATED, '订单已生成', occurred_at=order.created_at)


def sync_timeline_from_order_fields(order: BuyOrder) -> None:
    """把已有时间戳字段补写入历程（兼容 83 之前订单）。"""
    from .models import OrderTimelineEvent

    def _ensure(code, label, dt):
        if not dt:
            return
        if order.timeline_events.filter(event_code=code).exists():
            return
        OrderTimelineEvent.objects.create(
            order=order, event_code=code, label=label, occurred_at=dt,
        )

    record_order_created(order)
    _ensure(TL_PAYMENT_RECEIVED, '已支付', order.payment_time)
    _ensure(TL_PREP_STARTED, '开始备货', order.preparing_at)
    if order.ready_at:
        if order.is_basic_order():
            lbl = '已备货'
        elif order.is_dine_in():
            lbl = '已出餐'
        elif order.is_takeaway():
            lbl = '已备好待取'
        else:
            lbl = '出餐可配送'
        _ensure(TL_READY, lbl, order.ready_at)
    _ensure(TL_GOODS_DELIVERED, '商品已全部交付', order.goods_delivered_at)
    _ensure(TL_ORDER_COMPLETED, '订单已完成', order.completed_at)
    delivery = getattr(order, 'delivery_order', None)
    if delivery:
        _ensure(TL_DELIVERY_ACCEPTED, '骑手已接单', delivery.accepted_at)
        _ensure(TL_DELIVERY_PICKED_UP, '骑手已取餐', delivery.picked_up_at)
        _ensure(TL_DELIVERY_STARTED, '开始送餐', delivery.in_transit_at)
        _ensure(TL_DELIVERY_COMPLETED, '已送达', delivery.completed_at)
    if order.cancelled_at or order.order_status == 'cancelled':
        side = ''
        if order.cancel_side == 'buyer':
            side = '（买家）'
        elif order.cancel_side == 'shop':
            side = '（店家）'
        _ensure(TL_ORDER_CANCELLED, f'订单已取消{side}', order.cancelled_at)


def _buyer_timeline_label(order: BuyOrder, event_code: str, label: str) -> str:
    """客人端整单文案：堂食「已出餐」改为「就餐中」。"""
    if event_code == TL_READY and order.is_dine_in() and label == '已出餐':
        return '就餐中'
    return label


def build_order_timeline(order: BuyOrder, *, viewer: str = VIEWER_BUYER) -> list[tuple[str, object]]:
    """按角色返回 (标签, 时间) 列表；无时间的不展示。"""
    sync_timeline_from_order_fields(order)
    allowed = _viewer_codes(viewer)
    delivery = getattr(order, 'delivery_order', None)
    rows: list[tuple[str, object]] = []
    qs = order.timeline_events.order_by('occurred_at', 'pk')
    for ev in qs:
        if allowed is not None and ev.event_code not in allowed:
            continue
        # 外卖：骑手取餐前不展示「商品已全部交付」（避免时间线逻辑颠倒）
        if (
            ev.event_code == TL_GOODS_DELIVERED
            and order.fulfillment_type == 'delivery'
            and delivery
            and not delivery.picked_up_at
        ):
            continue
        rows.append((
            _buyer_timeline_label(order, ev.event_code, ev.label)
            if allowed is _BUYER_CODES
            else ev.label,
            ev.occurred_at,
        ))

    if _should_show_estimated_ready(order):
        est_label = _estimated_ready_label(order)
        if not any(lbl == est_label for lbl, _ in rows):
            rows.append((est_label, order.estimated_ready_at))

    if _should_show_estimated_delivery(order, delivery) and viewer in (
        VIEWER_BUYER, VIEWER_SELLER, VIEWER_STAFF, VIEWER_WORK,
    ):
        if not any(lbl == '预计送达' for lbl, _ in rows):
            rows.append(('预计送达', delivery.estimated_delivery_time))

    rows.sort(key=_timeline_sort_key)
    return rows
