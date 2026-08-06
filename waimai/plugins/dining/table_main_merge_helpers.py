# 桌码主单加点加锁（幂等第 8 步 · 并发合并）
# 同桌同时下单时：锁桌台会话 + 锁订单行，再合并菜品，避免覆盖丢失

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Callable

from django.db import transaction

from waimai.models import BuyOrder
from waimai.product_helpers import PRICE_TIER_GENERAL


def _merge_dish_items(existing_items, cart_items) -> list[dict]:
    """把购物车行合并进订单 dish_items（内存计算，不写库）。"""
    dish_map = {}
    for row in existing_items or []:
        did = str(row.get('dish_id', '')).replace('-', '')
        tier = row.get('price_tier', PRICE_TIER_GENERAL)
        dish_map[f'{did}:{tier}'] = dict(row)

    for item in cart_items:
        did = item['dish'].dish_id.hex
        tier = item.get('price_tier', PRICE_TIER_GENERAL)
        map_key = f'{did}:{tier}'
        if map_key in dish_map:
            dish_map[map_key]['quantity'] = (
                int(dish_map[map_key].get('quantity', 0)) + item['quantity']
            )
        else:
            dish_map[map_key] = {
                'line_id': uuid.uuid4().hex,
                'dish_id': did,
                'name': item['dish'].name,
                'price': float(item['unit_price']),
                'quantity': item['quantity'],
                'price_tier': tier,
                'prepared_count': 0,
                'served_count': 0,
            }
    return list(dish_map.values())


def _apply_cart_merge_to_order(
    order: BuyOrder,
    cart_items,
    seller_id: str,
    distance_km,
    fulfillment_type: str,
) -> BuyOrder | None:
    """在已加锁的订单对象上合并购物车并重算金额；失败返回 None。"""
    from waimai.channel_helpers import build_order_pricing

    merged_items = _merge_dish_items(order.dish_items, cart_items)
    subtotal = sum(
        Decimal(str(r['price'])) * r['quantity'] for r in merged_items
    )
    delivery_fee, fee_detail = build_order_pricing(
        seller_id, subtotal, distance_km, fulfillment_type,
    )
    if delivery_fee is None:
        return None
    order.dish_items = merged_items
    order.subtotal_amount = subtotal
    order.delivery_fee = delivery_fee
    order.delivery_fee_detail = fee_detail
    order.total_amount = subtotal + delivery_fee
    order.save(update_fields=[
        'dish_items', 'subtotal_amount', 'delivery_fee',
        'delivery_fee_detail', 'total_amount', 'updated_at',
    ])
    return order


def _pending_main_order_for_session(session):
    """会话下仍可加点合并的进行中单。"""
    from .table_helpers import get_open_order_for_session

    open_order = get_open_order_for_session(session)
    if not open_order:
        return None
    if open_order.payment_status != 'pending_payment':
        return None
    if open_order.order_status in ('completed', 'cancelled'):
        return None
    return open_order


@transaction.atomic
def merge_cart_into_table_main_order(
    table_session,
    cart_items,
    seller_id: str,
    distance_km,
    fulfillment_type: str,
) -> BuyOrder | None:
    """
    桌码主单：锁会话 + 锁订单后合并加点。
    无可合并单或计价失败时返回 None。
    """
    from waimai.dine_models import TableSession

    locked_sess = TableSession.objects.select_for_update().get(
        pk=table_session.pk,
    )
    if locked_sess.status != 'open':
        return None
    pending = _pending_main_order_for_session(locked_sess)
    if not pending:
        return None
    order = BuyOrder.objects.select_for_update().get(pk=pending.pk)
    if order.payment_status != 'pending_payment':
        return None
    return _apply_cart_merge_to_order(
        order, cart_items, seller_id, distance_km, fulfillment_type,
    )


@transaction.atomic
def place_or_merge_table_main_order(
    table_session,
    cart_items,
    seller_id: str,
    distance_km,
    fulfillment_type: str,
    create_order_fn: Callable[[], BuyOrder],
) -> tuple[str, BuyOrder | None]:
    """
    桌码主单下单入口：优先合并待支付单；否则在同一会话锁内新建。
    返回 ('merged'|'created', order) 或 ('failed', None)。
    """
    from waimai.dine_models import TableSession

    locked_sess = TableSession.objects.select_for_update().get(
        pk=table_session.pk,
    )
    if locked_sess.status != 'open':
        return 'failed', None

    pending = _pending_main_order_for_session(locked_sess)
    if pending:
        order = BuyOrder.objects.select_for_update().get(pk=pending.pk)
        merged = _apply_cart_merge_to_order(
            order, cart_items, seller_id, distance_km, fulfillment_type,
        )
        if merged is None:
            return 'failed', None
        return 'merged', merged

    order = create_order_fn()
    if order.table_session_id != locked_sess.pk:
        order.table_session = locked_sess
        order.save(update_fields=['table_session', 'updated_at'])
    return 'created', order
