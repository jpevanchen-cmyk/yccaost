# 履约包：骑手取餐 / 开始送餐 / 送达 — 配送线与主状态同步（§5.6 · 进度 82-②）
# 骑手相关动作只在此模块改配送状态并同步主状态，避免 workbench 里重复写两套。

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from waimai.models import DeliveryOrder
from waimai.order_status_transition_helpers import check_order_status_transition
from waimai.order_status_event_helpers import (
    EVENT_DELIVERY_COMPLETED,
    EVENT_DELIVERY_PICKED_UP,
    EVENT_DELIVERY_STARTED,
    handle_order_status_event,
)

# 允许点「我已送达」的配送状态
RIDER_COMPLETABLE_DELIVERY_STATUSES = frozenset({'in_transit', 'overtime'})

# 可取餐 / 登记现金的配送状态
RIDER_POST_PICKUP_STATUSES = frozenset({'picked_up', 'in_transit', 'overtime'})

_VIOLATION_HINTS = {
    'delivery_pickup_should_be_awaiting_delivery': '取餐后应进入「待配送」，不能直接变成「配送中」。',
    'invalid_transition': '订单主状态不允许这样变更。',
    'awaiting_delivery_bad_from': '「待配送」须从「待取货」或「配送中」回退进入。',
    'non_delivery_delivery_status': '非外卖单不能使用配送专属主状态。',
    'deprecated_status_write': '不应再写入已废止的主状态。',
}


def violation_hint(code: str) -> str:
    if not code:
        return '订单状态变更被拒绝。'
    first = code.split(',')[0].strip()
    return _VIOLATION_HINTS.get(first, '订单状态变更被拒绝。')


def rider_has_in_transit_order(rider_id: str, *, exclude_delivery_id=None) -> bool:
    """同一骑手是否已有另一单在「配送中」。"""
    qs = DeliveryOrder.objects.filter(
        rider_id=rider_id,
        delivery_status='in_transit',
    )
    if exclude_delivery_id:
        qs = qs.exclude(delivery_id=exclude_delivery_id)
    return qs.exists()


@transaction.atomic
def apply_rider_pickup(delivery: DeliveryOrder) -> tuple[bool, str]:
    """骑手确认取餐：配送「已取餐」+ 主状态「待配送」。"""
    delivery = (
        DeliveryOrder.objects.select_for_update()
        .select_related('buy_order')
        .get(pk=delivery.pk)
    )
    if delivery.delivery_status != 'accepted':
        return False, '当前状态不能取餐'

    from waimai.waiter_helpers import delivery_handoff_ready

    buy = delivery.buy_order
    if not delivery_handoff_ready(buy):
        return False, '餐品尚未交接完成，请稍后再取'

    ok, violations = check_order_status_transition(
        buy, buy.order_status or '', 'awaiting_delivery',
        source='delivery_workflow_helpers.apply_rider_pickup',
    )
    if not ok:
        return False, violation_hint(','.join(violations))

    fields = handle_order_status_event(
        buy,
        EVENT_DELIVERY_PICKED_UP,
        source='delivery_workflow_helpers.apply_rider_pickup',
    )
    if buy.order_status != 'awaiting_delivery':
        return False, violation_hint('invalid_transition')

    delivery.delivery_status = 'picked_up'
    delivery.picked_up_at = timezone.now()
    delivery.save(update_fields=['delivery_status', 'picked_up_at', 'updated_at'])
    buy.save(update_fields=list(dict.fromkeys(fields)) or ['order_status', 'updated_at'])
    return True, '已确认取餐'


@transaction.atomic
def apply_rider_start_delivery(delivery: DeliveryOrder) -> tuple[bool, str]:
    """骑手开始送餐：配送「配送中」+ 主状态「配送中」；同一时刻仅一单配送中。"""
    delivery = (
        DeliveryOrder.objects.select_for_update()
        .select_related('buy_order')
        .get(pk=delivery.pk)
    )
    if delivery.delivery_status != 'picked_up':
        return False, '请先取餐，再点开始送餐'

    rider_id = (delivery.rider_id or '').strip()
    if rider_id and rider_has_in_transit_order(rider_id, exclude_delivery_id=delivery.delivery_id):
        return False, '您已有另一单正在配送中，请先送达后再开始本单'

    buy = delivery.buy_order
    ok, violations = check_order_status_transition(
        buy, buy.order_status or '', 'delivering',
        source='delivery_workflow_helpers.apply_rider_start_delivery',
    )
    if not ok:
        return False, violation_hint(','.join(violations))

    fields = handle_order_status_event(
        buy,
        EVENT_DELIVERY_STARTED,
        source='delivery_workflow_helpers.apply_rider_start_delivery',
    )
    if buy.order_status != 'delivering':
        return False, violation_hint('invalid_transition')

    delivery.delivery_status = 'in_transit'
    delivery.in_transit_at = timezone.now()
    delivery.save(update_fields=['delivery_status', 'in_transit_at', 'updated_at'])
    buy.save(update_fields=list(dict.fromkeys(fields)) or ['order_status', 'updated_at'])
    return True, '已开始送餐'


@transaction.atomic
def apply_rider_complete_delivery(delivery: DeliveryOrder) -> tuple[bool, str]:
    """骑手确认送达：配送「已送达」+ 主状态「已完成」（须已收款或在线已付）。"""
    delivery = (
        DeliveryOrder.objects.select_for_update()
        .select_related('buy_order')
        .get(pk=delivery.pk)
    )
    if delivery.delivery_status not in RIDER_COMPLETABLE_DELIVERY_STATUSES:
        return False, '请先点「开始送餐」，送达后再点「我已送达」'

    buy = delivery.buy_order
    if buy.is_cod_awaiting_collection():
        return False, '这是货到付款单，请先确认收到现金（或顾客已扫码付款）再点已送达'

    fields = handle_order_status_event(
        buy,
        EVENT_DELIVERY_COMPLETED,
        source='delivery_workflow_helpers.apply_rider_complete_delivery',
    )
    if buy.order_status != 'completed':
        return False, '订单尚不能标记为已完成（请确认已收款）'

    now = timezone.now()
    delivery.delivery_status = 'completed'
    delivery.completed_at = now
    delivery.save(update_fields=['delivery_status', 'completed_at', 'updated_at'])
    buy.save(update_fields=list(dict.fromkeys(fields)) or ['order_status', 'updated_at'])
    return True, '已确认送达'
