# 订单主状态统一守门员（进度 82 · 第二步：拦截模式）
# 正本规则：E 盘开发方案 §5.6；违规拒绝写入。

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import BuyOrder

logger = logging.getLogger('waimai.order_status')

# 观察守门：违规仍写入，只记 warning 日志
GUARD_MODE_OBSERVE = 'observe'
# 第二步施工启用：违规拒绝写入
GUARD_MODE_ENFORCE = 'enforce'

# 第二步：违规拒绝写入（82-③ 已完成：完成汇合一处化，见 order_status_event_helpers）
ORDER_STATUS_GUARD_MODE = GUARD_MODE_ENFORCE

# 82-③ 已合并至 order_status_event_helpers.try_complete_order / handle_order_status_event
DEDUP_STEP3_SOURCES = (
    'order_desk_helpers.sync_order_desk_progress',
    'waiter_helpers.sync_waiter_service_status',
    'kitchen_helpers.sync_kitchen_progress',
    'payments.service',
    'waiter_handlers',
    'workbench_handlers',
)

# 目标态主状态（§5.6.2）
TARGET_ORDER_STATUSES = frozenset({
    'created',
    'awaiting_prep',
    'preparing',
    'ready_pickup',
    'awaiting_delivery',
    'delivering',
    'completed',
    'cancelled',
})

# 旧库内仍可能出现的值；新写入应逐步淘汰
LEGACY_ORDER_STATUSES = frozenset({
    'awaiting_payment',
    'awaiting_shop_confirm',
})

TERMINAL_ORDER_STATUSES = frozenset({'completed', 'cancelled'})

# 买家可自主取消的主状态（§5.6.8 方案 B · 与主状态机同处维护）
BUYER_SELF_CANCELABLE_STATUSES = frozenset({
    'created',
    'awaiting_payment',
    'awaiting_shop_confirm',
    'awaiting_prep',
})


def buyer_can_self_cancel_order(order: BuyOrder) -> bool:
    """买家能否自主取消：查主状态规则表。"""
    if order.order_status == 'cancelled':
        return False
    return order.order_status in BUYER_SELF_CANCELABLE_STATUSES

# 第一步：在「目标规则」之外，仍允许现网已有跳转，避免日志洪水；重点抓 §5.6 明确违规
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    'created': frozenset({'awaiting_prep', 'cancelled'}),
    'awaiting_payment': frozenset({'awaiting_prep', 'preparing', 'ready_pickup', 'cancelled'}),
    'awaiting_shop_confirm': frozenset({'awaiting_prep', 'preparing', 'ready_pickup', 'cancelled'}),
    'awaiting_prep': frozenset({'preparing', 'ready_pickup', 'awaiting_delivery', 'completed', 'cancelled'}),
    'preparing': frozenset({'awaiting_prep', 'ready_pickup', 'awaiting_delivery', 'completed', 'cancelled'}),
    'ready_pickup': frozenset({
        'preparing', 'awaiting_delivery', 'completed', 'cancelled',
    }),
    'awaiting_delivery': frozenset({'delivering', 'ready_pickup', 'completed', 'cancelled'}),
    'delivering': frozenset({'awaiting_delivery', 'completed', 'cancelled'}),
    'completed': frozenset({'cancelled'}),
    'cancelled': frozenset(),
}


def _order_fulfillment(order: BuyOrder) -> str:
    return getattr(order, 'fulfillment_type', '') or ''


def check_order_status_transition(
    order: BuyOrder,
    old_status: str,
    new_status: str,
    *,
    source: str = '',
) -> tuple[bool, list[str]]:
    """
    对照 §5.6 目标规则检查主状态变更是否合规。
    返回 (是否完全合规, 违规代码列表)。
    """
    old_status = (old_status or '').strip()
    new_status = (new_status or '').strip()
    if old_status == new_status:
        return True, []

    violations: list[str] = []

    if new_status in LEGACY_ORDER_STATUSES:
        violations.append('deprecated_status_write')

    if new_status not in TARGET_ORDER_STATUSES and new_status not in LEGACY_ORDER_STATUSES:
        violations.append('unknown_status')

    allowed = _ALLOWED_TRANSITIONS.get(old_status)
    if allowed is not None and new_status not in allowed:
        violations.append('invalid_transition')
    elif allowed is None and old_status:
        violations.append('unknown_from_status')

    fulfillment = _order_fulfillment(order)

    # 外卖：取餐后应进「待配送」，不能直接「配送中」
    if fulfillment == 'delivery' and new_status == 'delivering':
        if old_status in ('ready_pickup', 'awaiting_prep', 'preparing', 'awaiting_shop_confirm', 'awaiting_payment'):
            violations.append('delivery_pickup_should_be_awaiting_delivery')

    # 非外卖不应出现配送专属主状态
    if fulfillment != 'delivery' and new_status in ('awaiting_delivery', 'delivering'):
        violations.append('non_delivery_delivery_status')

    # 外卖「待配送」须从「待取货」来（或从配送中回退）
    if fulfillment == 'delivery' and new_status == 'awaiting_delivery':
        if old_status not in ('ready_pickup', 'delivering'):
            violations.append('awaiting_delivery_bad_from')

    return (len(violations) == 0), violations


def transition_order_status(
    order: BuyOrder,
    new_status: str,
    *,
    source: str = '',
    mode: str | None = None,
) -> tuple[bool, str]:
    """
    统一写入 BuyOrder.order_status。
    观察模式：违规仍写入，记 warning；返回 (是否合规, 违规码拼接)。
    拦截模式（第二步）：违规拒绝写入。
    """
    old_status = order.order_status or ''
    new_status = (new_status or '').strip()
    if old_status == new_status:
        return True, ''

    mode = mode or ORDER_STATUS_GUARD_MODE
    ok, violations = check_order_status_transition(
        order, old_status, new_status, source=source,
    )

    if violations:
        order_no = ''
        try:
            order_no = order.get_display_order_no()
        except Exception:
            order_no = str(getattr(order, 'order_id', '') or '')
        logger.warning(
            '订单主状态守门[%s] %s %s→%s source=%s violations=%s',
            mode,
            order_no,
            old_status,
            new_status,
            source or '-',
            ','.join(violations),
        )

    if not ok and mode == GUARD_MODE_ENFORCE:
        return False, ','.join(violations)

    order.order_status = new_status
    return ok, ','.join(violations)


def transition_order_status_if_changed(
    order: BuyOrder,
    new_status: str,
    *,
    source: str = '',
    mode: str | None = None,
) -> tuple[bool, list[str]]:
    """
    若状态有变则走守门写入；返回 (是否合规, 建议追加的 update_fields 列表)。
    供 sync_* 与 save 前批量更新用。
    """
    old_status = order.order_status or ''
    new_status = (new_status or '').strip()
    if old_status == new_status:
        return True, []

    ok, _ = transition_order_status(order, new_status, source=source, mode=mode)
    return ok, ['order_status']
