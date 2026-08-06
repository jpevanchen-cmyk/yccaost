# 订单主状态事件表（进度 82-③ · 事件化）
# 支付 / 配送 / 备制只发事件；「已完成」只在 try_complete_order 一处汇合。
# 正本规则：E 盘开发方案 §5.6。

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .order_status_transition_helpers import (
    TERMINAL_ORDER_STATUSES,
    transition_order_status_if_changed,
)

if TYPE_CHECKING:
    from .models import BuyOrder

logger = logging.getLogger('waimai.order_status')

# 事件名（对齐开发方案 §5.6）
EVENT_PAYMENT_RECEIVED = 'PaymentReceived'
EVENT_PAYMENT_UNCOLLECTED_CLOSE = 'PaymentUncollectedClose'
EVENT_PREP_PROGRESS = 'PrepProgressUpdated'
EVENT_GOODS_FULLY_DELIVERED = 'GoodsFullyDelivered'
EVENT_DELIVERY_PICKED_UP = 'DeliveryPickedUp'
EVENT_DELIVERY_STARTED = 'DeliveryStarted'
EVENT_DELIVERY_COMPLETED = 'DeliveryCompleted'
EVENT_MANUAL_COMPLETE = 'ManualCompleteRequested'

# 下单后、尚未选支付方式的主状态
UNPAID_ENTRY_STATUSES = frozenset({
    'created',
    'awaiting_payment',
    'awaiting_shop_confirm',
})


def payment_allows_order_completion(order: BuyOrder) -> bool:
    """钱齐：已收齐，或未收款结案。"""
    return order.payment_status in ('paid', 'uncollected')


def payment_blocks_completion(order: BuyOrder) -> bool:
    """少收争议等阻塞完成类事件。"""
    return bool(
        order.cash_exception_unresolved()
        or order.cash_shortfall_waiting_buyer()
    )


def goods_fulfilled_for_completion(
    order: BuyOrder,
    *,
    delivery_confirmed: bool = False,
    manual_complete: bool = False,
) -> bool:
    """货齐：按履约类型判断。"""
    if order.fulfillment_type == 'delivery':
        return delivery_confirmed

    # 堂食：上菜齐不算用餐结束，须员工手动「用餐完成」
    if order.is_dine_in():
        if not manual_complete:
            return False
        if order.order_status == 'ready_pickup':
            return True
        return _all_goods_served(order)

    if manual_complete:
        if order.order_status == 'ready_pickup':
            return True
        if order.is_basic_order() or order.is_in_store() or order.fulfillment_type == 'order':
            return _all_goods_served(order)
        return False

    return _all_goods_served(order)


def _all_goods_served(order: BuyOrder) -> bool:
    """按份进度：全部交付/上桌/处理完成。"""
    if order.is_basic_order() or order.fulfillment_type == 'order':
        from .order_desk_helpers import count_basic_delivered_units

        total, served = count_basic_delivered_units(order)
    else:
        from .waiter_helpers import count_order_units

        total, served = count_order_units(order.dish_items)
    return total > 0 and served >= total


def try_complete_order(
    order: BuyOrder,
    *,
    source: str,
    delivery_confirmed: bool = False,
    manual_complete: bool = False,
) -> list[str]:
    """
    统一「已完成」汇合口：货齐 + 钱齐才写 completed。
    返回需 save 的字段名。
    """
    if order.order_status in TERMINAL_ORDER_STATUSES:
        return []

    if payment_blocks_completion(order):
        return []

    if not payment_allows_order_completion(order):
        return []

    if not goods_fulfilled_for_completion(
        order,
        delivery_confirmed=delivery_confirmed,
        manual_complete=manual_complete,
    ):
        return []

    _, extra = transition_order_status_if_changed(
        order, 'completed', source=source,
    )
    if not extra:
        return []

    from django.utils import timezone

    if getattr(order, 'pk', None):
        if not getattr(order, 'completed_at', None):
            order.completed_at = timezone.now()
            extra.append('completed_at')

    if order.is_dine_in():
        from .plugins.dining.guest_order_helpers import maybe_close_table_session_after_settle

        maybe_close_table_session_after_settle(order)

    return extra + ['updated_at']


def apply_prep_progress_event(order: BuyOrder, *, source: str) -> list[str]:
    """备制进度：只刷新 preparing / ready_pickup，不直接 completed。"""
    from django.utils import timezone

    if order.is_basic_order():
        from .order_desk_helpers import (
            count_basic_delivered_units,
            count_basic_processed_units,
        )

        total, prepared = count_basic_processed_units(order)
        _, _served = count_basic_delivered_units(order)
    else:
        from .kitchen_helpers import count_kitchen_units

        total, prepared = count_kitchen_units(order)

    if total <= 0:
        return []

    update_fields: list[str] = []

    if prepared > 0 and order.order_status == 'awaiting_prep':
        _, extra = transition_order_status_if_changed(
            order, 'preparing', source=source,
        )
        update_fields.extend(extra)
        if not order.preparing_at:
            order.preparing_at = timezone.now()
            update_fields.append('preparing_at')

    if prepared >= total and order.order_status in ('awaiting_prep', 'preparing'):
        _, extra = transition_order_status_if_changed(
            order, 'ready_pickup', source=source,
        )
        update_fields.extend(extra)
        if 'order_status' in extra:
            order.ready_at = timezone.now()
            update_fields.append('ready_at')

    if prepared < total and order.order_status == 'ready_pickup':
        _, extra = transition_order_status_if_changed(
            order, 'preparing', source=f'{source}.rollback',
        )
        update_fields.extend(extra)
        if 'order_status' in extra and order.ready_at is not None:
            order.ready_at = None
            update_fields.append('ready_at')

    if update_fields:
        update_fields.append('updated_at')
    return list(dict.fromkeys(update_fields))


def apply_goods_delivered_side_effects(order: BuyOrder, *, source: str) -> list[str]:
    """货已齐但未收款：店内单进入待取走/待结账。"""
    update_fields: list[str] = []
    if (
        order.is_in_store()
        and order.order_status in ('awaiting_prep', 'preparing')
        and _all_goods_served(order)
    ):
        _, extra = transition_order_status_if_changed(
            order, 'ready_pickup', source=source,
        )
        update_fields.extend(extra)
    return update_fields


def handle_order_status_event(
    order: BuyOrder,
    event: str,
    *,
    source: str,
    delivery_confirmed: bool = False,
    manual_complete: bool = False,
) -> list[str]:
    """主状态机事件入口；返回需 save 的字段名。"""
    update_fields: list[str] = []

    if event == EVENT_PAYMENT_RECEIVED:
        if order.order_status in UNPAID_ENTRY_STATUSES:
            _, extra = transition_order_status_if_changed(
                order, 'awaiting_prep', source=source,
            )
            update_fields.extend(extra)
        update_fields.extend(
            try_complete_order(order, source=f'{source}.after_payment'),
        )

    elif event == EVENT_PREP_PROGRESS:
        update_fields.extend(apply_prep_progress_event(order, source=source))

    elif event == EVENT_GOODS_FULLY_DELIVERED:
        from django.utils import timezone

        if _all_goods_served(order) and not getattr(order, 'goods_delivered_at', None):
            order.goods_delivered_at = timezone.now()
            update_fields.append('goods_delivered_at')
        update_fields.extend(
            apply_goods_delivered_side_effects(order, source=source),
        )
        update_fields.extend(
            try_complete_order(order, source=source),
        )

    elif event == EVENT_DELIVERY_PICKED_UP:
        _, extra = transition_order_status_if_changed(
            order, 'awaiting_delivery', source=source,
        )
        update_fields.extend(extra)

    elif event == EVENT_DELIVERY_STARTED:
        _, extra = transition_order_status_if_changed(
            order, 'delivering', source=source,
        )
        update_fields.extend(extra)

    elif event == EVENT_DELIVERY_COMPLETED:
        update_fields.extend(
            try_complete_order(
                order,
                source=source,
                delivery_confirmed=True,
            ),
        )

    elif event == EVENT_PAYMENT_UNCOLLECTED_CLOSE:
        update_fields.extend(
            try_complete_order(
                order,
                source=source,
                manual_complete=True,
            ),
        )

    elif event == EVENT_MANUAL_COMPLETE:
        update_fields.extend(
            try_complete_order(
                order,
                source=source,
                manual_complete=True,
            ),
        )

    else:
        logger.warning('未知订单主状态事件 %s source=%s', event, source)

    if update_fields:
        update_fields.append('updated_at')
    return list(dict.fromkeys(update_fields))
