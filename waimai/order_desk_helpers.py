# 主体通用订单台：处理基础「下单」通道，不依赖饮食插件。

from __future__ import annotations

from django.utils import timezone

from .models import BuyOrder
from .order_progress_helpers import (
    build_dual_progress_groups,
    build_progress_groups,
    count_progress_units,
    fill_all_progress_units,
    find_markable_line,
    find_undo_line,
    norm_dish_id,
    normalize_dish_items,
)

# 主体订单台可推进的履约状态
ACTIVE_BASIC_STATUSES = (
    'awaiting_prep',
    'preparing',
    'ready_pickup',
)

_BASIC_PROGRESS_FIELDS = ('prepared_count', 'served_count')


def _normalize_basic_dish_items(dish_items):
    return normalize_dish_items(dish_items, _BASIC_PROGRESS_FIELDS)


def persist_basic_dish_items_if_needed(order: BuyOrder) -> None:
    """旧订单首次展示时补齐按件进度字段并落库。"""
    items, changed = _normalize_basic_dish_items(order.dish_items)
    if changed:
        order.dish_items = items
        order.save(update_fields=['dish_items', 'updated_at'])


def count_basic_processed_units(order: BuyOrder) -> tuple[int, int]:
    """返回 (总份数, 已处理份数)。"""
    return count_progress_units(order.dish_items, 'prepared_count')


def count_basic_delivered_units(order: BuyOrder) -> tuple[int, int]:
    """返回 (总份数, 已交付份数)。"""
    return count_progress_units(order.dish_items, 'served_count')


def build_order_desk_item_rows(order: BuyOrder) -> list[dict]:
    """通用订单台：每种商品的处理/交付进度。"""
    return build_dual_progress_groups(order.dish_items)


def sync_order_desk_progress(order: BuyOrder) -> list[str]:
    """按件进度刷新整单状态；全部交付且已收款后自动完成。"""
    total, prepared = count_basic_processed_units(order)
    _, served = count_basic_delivered_units(order)
    if total <= 0:
        return []

    update_fields: list[str] = []

    if prepared > 0 and order.order_status == 'awaiting_prep':
        order.order_status = 'preparing'
        update_fields.append('order_status')
        if not order.preparing_at:
            order.preparing_at = timezone.now()
            update_fields.append('preparing_at')

    if prepared >= total and order.order_status in ('awaiting_prep', 'preparing'):
        order.order_status = 'ready_pickup'
        order.ready_at = timezone.now()
        update_fields.extend(['order_status', 'ready_at'])

    if prepared < total and order.order_status == 'ready_pickup':
        order.order_status = 'preparing'
        update_fields.append('order_status')

    if served >= total and order.payment_status == 'paid':
        order.order_status = 'completed'
        update_fields.append('order_status')

    if update_fields:
        update_fields.append('updated_at')
    return list(dict.fromkeys(update_fields))


def _basic_order_can_operate(order: BuyOrder) -> bool:
    return (
        order.is_basic_order()
        and order.order_status in ACTIVE_BASIC_STATUSES
        and order.payment_status in ('paid', 'pending_payment')
    )


def basic_order_can_mark_item_processed(order: BuyOrder) -> bool:
    total, prepared = count_basic_processed_units(order)
    return _basic_order_can_operate(order) and total > 0 and prepared < total


def basic_order_can_mark_item_delivered(order: BuyOrder) -> bool:
    if not _basic_order_can_operate(order):
        return False
    items, _ = _normalize_basic_dish_items(order.dish_items)
    for line in items:
        prepared = int(line.get('prepared_count') or 0)
        served = int(line.get('served_count') or 0)
        if served < prepared:
            return True
    return False


def basic_order_can_mark_all_processed(order: BuyOrder) -> bool:
    return basic_order_can_mark_item_processed(order)


def basic_order_can_mark_all_delivered(order: BuyOrder) -> bool:
    return basic_order_can_mark_item_delivered(order)


def mark_basic_item_processed(
    order: BuyOrder,
    dish_id: str,
    *,
    actor,
) -> tuple[bool, str]:
    """标记某商品再处理一份。"""
    if not _basic_order_can_operate(order):
        return False, '当前订单不能按件处理'
    items, _ = _normalize_basic_dish_items(order.dish_items)
    line = find_markable_line(items, dish_id, 'prepared_count')
    if not line:
        return False, '该商品已全部处理，无需重复操作'

    line['prepared_count'] = int(line.get('prepared_count') or 0) + 1
    order.dish_items = items
    groups = build_progress_groups(items, 'prepared_count', 'prepared_qty')
    group = next((g for g in groups if g['dish_id'] == norm_dish_id(dish_id)), None)
    prepared_after = group['prepared_qty'] if group else 0
    total_qty = group['total_qty'] if group else 0
    dish_name = group['name'] if group else line.get('name', '商品')

    update_fields = ['dish_items', 'updated_at']
    update_fields.extend(sync_order_desk_progress(order))
    order.save(update_fields=list(dict.fromkeys(update_fields)))

    from .audit_helpers import audit_order_status

    audit_order_status(
        order=order,
        actor=actor,
        summary=(
            f'处理商品「{dish_name}」1 份'
            f'（{prepared_after}/{total_qty}）· {order.get_display_order_no()}'
        ),
    )
    return True, f'「{dish_name}」已处理 1 份（{prepared_after}/{total_qty}）'


def undo_basic_item_processed(
    order: BuyOrder,
    dish_id: str,
    *,
    actor,
) -> tuple[bool, str]:
    """撤回某商品最近一份处理。"""
    if not _basic_order_can_operate(order):
        return False, '当前订单不能撤回处理'
    items, _ = _normalize_basic_dish_items(order.dish_items)
    line = find_undo_line(items, dish_id, 'prepared_count')
    if not line:
        return False, '该商品尚未处理，无法撤回'

    served = int(line.get('served_count') or 0)
    prepared = int(line.get('prepared_count') or 0)
    if prepared <= served:
        return False, '该商品已有交付记录，请先撤回交付再撤回处理'

    line['prepared_count'] = prepared - 1
    order.dish_items = items
    groups = build_progress_groups(items, 'prepared_count', 'prepared_qty')
    group = next((g for g in groups if g['dish_id'] == norm_dish_id(dish_id)), None)
    prepared_after = group['prepared_qty'] if group else 0
    total_qty = group['total_qty'] if group else 0
    dish_name = group['name'] if group else line.get('name', '商品')

    update_fields = ['dish_items', 'updated_at']
    update_fields.extend(sync_order_desk_progress(order))
    order.save(update_fields=list(dict.fromkeys(update_fields)))

    from .audit_helpers import audit_order_status

    audit_order_status(
        order=order,
        actor=actor,
        summary=(
            f'撤回处理「{dish_name}」1 份'
            f'（现为 {prepared_after}/{total_qty}）· {order.get_display_order_no()}'
        ),
    )
    return True, f'已撤回「{dish_name}」1 份处理（现为 {prepared_after}/{total_qty}）'


def _find_deliverable_line(items: list[dict], dish_id: str) -> dict | None:
    """找还可交付的一份（须已处理且未交付）。"""
    target = norm_dish_id(dish_id)
    for line in items:
        if norm_dish_id(str(line.get('dish_id', ''))) != target:
            continue
        if int(line.get('served_count') or 0) < int(line.get('prepared_count') or 0):
            return line
    return None


def mark_basic_item_delivered(
    order: BuyOrder,
    dish_id: str,
    *,
    actor,
) -> tuple[bool, str]:
    """标记某商品再交付一份（须先处理）。"""
    if not _basic_order_can_operate(order):
        return False, '当前订单不能按件交付'
    items, _ = _normalize_basic_dish_items(order.dish_items)
    line = _find_deliverable_line(items, dish_id)
    if not line:
        prepared_left = False
        target = norm_dish_id(dish_id)
        for row in items:
            if norm_dish_id(str(row.get('dish_id', ''))) != target:
                continue
            if int(row.get('served_count') or 0) < int(row.get('quantity') or 0):
                prepared_left = True
                break
        if not prepared_left:
            return False, '该商品已全部交付，无需重复操作'
        return False, '请先处理这一份，再交付'

    line['served_count'] = int(line.get('served_count') or 0) + 1
    order.dish_items = items
    groups = build_progress_groups(items, 'served_count', 'served_qty')
    group = next((g for g in groups if g['dish_id'] == norm_dish_id(dish_id)), None)
    served_after = group['served_qty'] if group else 0
    total_qty = group['total_qty'] if group else 0
    dish_name = group['name'] if group else line.get('name', '商品')

    update_fields = ['dish_items', 'updated_at']
    update_fields.extend(sync_order_desk_progress(order))
    order.save(update_fields=list(dict.fromkeys(update_fields)))

    from .audit_helpers import audit_order_status

    audit_order_status(
        order=order,
        actor=actor,
        summary=(
            f'交付商品「{dish_name}」1 份'
            f'（{served_after}/{total_qty}）· {order.get_display_order_no()}'
        ),
    )
    msg = f'「{dish_name}」已交付 1 份（{served_after}/{total_qty}）'
    if (
        served_after >= total_qty
        and order.payment_method == 'cash'
        and order.payment_status == 'pending_payment'
    ):
        msg += '；请先确认已收现金，订单才会自动完成'
    return True, msg


def undo_basic_item_delivered(
    order: BuyOrder,
    dish_id: str,
    *,
    actor,
) -> tuple[bool, str]:
    """撤回某商品最近一份交付。"""
    if not _basic_order_can_operate(order):
        return False, '当前订单不能撤回交付'
    items, _ = _normalize_basic_dish_items(order.dish_items)
    line = find_undo_line(items, dish_id, 'served_count')
    if not line:
        return False, '该商品尚未交付，无法撤回'

    line['served_count'] = int(line.get('served_count') or 0) - 1
    order.dish_items = items
    groups = build_progress_groups(items, 'served_count', 'served_qty')
    group = next((g for g in groups if g['dish_id'] == norm_dish_id(dish_id)), None)
    served_after = group['served_qty'] if group else 0
    total_qty = group['total_qty'] if group else 0
    dish_name = group['name'] if group else line.get('name', '商品')

    update_fields = ['dish_items', 'updated_at']
    update_fields.extend(sync_order_desk_progress(order))
    order.save(update_fields=list(dict.fromkeys(update_fields)))

    from .audit_helpers import audit_order_status

    audit_order_status(
        order=order,
        actor=actor,
        summary=(
            f'撤回交付「{dish_name}」1 份'
            f'（现为 {served_after}/{total_qty}）· {order.get_display_order_no()}'
        ),
    )
    return True, f'已撤回「{dish_name}」1 份交付（现为 {served_after}/{total_qty}）'


def mark_all_basic_items_processed(order: BuyOrder, *, actor) -> tuple[bool, str]:
    """一键全部处理。"""
    if not _basic_order_can_operate(order):
        return False, '当前订单不能批量处理'
    items, _ = _normalize_basic_dish_items(order.dish_items)
    marked = fill_all_progress_units(items, 'prepared_count')
    if marked <= 0:
        return False, '所有商品已全部处理'

    order.dish_items = items
    update_fields = ['dish_items', 'updated_at']
    update_fields.extend(sync_order_desk_progress(order))
    order.save(update_fields=list(dict.fromkeys(update_fields)))

    from .audit_helpers import audit_order_status

    audit_order_status(
        order=order,
        actor=actor,
        summary=f'一键全部处理 {marked} 份 · {order.get_display_order_no()}',
    )
    return True, f'已一键处理 {marked} 份商品'


def mark_all_basic_items_delivered(order: BuyOrder, *, actor) -> tuple[bool, str]:
    """一键全部交付（仅交付已处理份数）。"""
    if not _basic_order_can_operate(order):
        return False, '当前订单不能批量交付'
    items, _ = _normalize_basic_dish_items(order.dish_items)
    marked = fill_all_progress_units(items, 'served_count', cap_field='prepared_count')
    if marked <= 0:
        return False, '没有可交付的商品，请先处理'

    order.dish_items = items
    update_fields = ['dish_items', 'updated_at']
    update_fields.extend(sync_order_desk_progress(order))
    order.save(update_fields=list(dict.fromkeys(update_fields)))

    from .audit_helpers import audit_order_status

    audit_order_status(
        order=order,
        actor=actor,
        summary=f'一键全部交付 {marked} 份 · {order.get_display_order_no()}',
    )
    msg = f'已一键交付 {marked} 份商品'
    if (
        order.payment_method == 'cash'
        and order.payment_status == 'pending_payment'
        and order.order_status != 'completed'
    ):
        msg += '；请先确认已收现金，订单才会自动完成'
    return True, msg


def basic_order_can_start(order: BuyOrder) -> bool:
    """是否可「开始处理」。"""
    return (
        order.is_basic_order()
        and order.order_status == 'awaiting_prep'
        and order.payment_status in ('paid', 'pending_payment')
    )


def basic_order_can_mark_ready(order: BuyOrder) -> bool:
    """是否可「标记可交付」。"""
    return order.is_basic_order() and order.order_status == 'preparing'


def basic_order_can_complete(order: BuyOrder) -> bool:
    """是否可「确认完成」（现金须先确认收款）。"""
    if not order.is_basic_order() or order.order_status != 'ready_pickup':
        return False
    if order.payment_method == 'cash' and order.payment_status == 'pending_payment':
        return False
    return order.payment_status == 'paid'


def basic_order_can_confirm_cash(order: BuyOrder) -> bool:
    """基础下单现金单是否可确认收款。"""
    return (
        order.is_basic_order()
        and order.payment_method == 'cash'
        and order.payment_status == 'pending_payment'
        and order.order_status in ACTIVE_BASIC_STATUSES
    )


def start_basic_order(order: BuyOrder, *, actor) -> tuple[bool, str]:
    """待备货 → 处理中。"""
    if not basic_order_can_start(order):
        return False, '当前订单不能开始处理'
    now = timezone.now()
    order.order_status = 'preparing'
    order.preparing_at = now
    order.save(update_fields=['order_status', 'preparing_at', 'updated_at'])
    from .audit_helpers import audit_order_status

    audit_order_status(
        order=order,
        actor=actor,
        summary=f'开始处理基础订单 {order.get_display_order_no()}',
    )
    return True, '已开始处理该订单'


def mark_basic_order_ready(order: BuyOrder, *, actor) -> tuple[bool, str]:
    """处理中 → 可交付。"""
    if not basic_order_can_mark_ready(order):
        return False, '当前订单不能标记为可交付'
    order.order_status = 'ready_pickup'
    order.ready_at = timezone.now()
    order.save(update_fields=['order_status', 'ready_at', 'updated_at'])
    from .audit_helpers import audit_order_status

    audit_order_status(
        order=order,
        actor=actor,
        summary=f'标记可交付 {order.get_display_order_no()}',
    )
    return True, '已标记为可交付'


def complete_basic_order(order: BuyOrder, *, actor) -> tuple[bool, str]:
    """可交付 → 已完成。"""
    if not basic_order_can_complete(order):
        if (
            order.is_basic_order()
            and order.order_status == 'ready_pickup'
            and order.payment_method == 'cash'
            and order.payment_status == 'pending_payment'
        ):
            return False, '请先确认已收到现金，再完成订单'
        return False, '当前订单不能确认完成'
    order.order_status = 'completed'
    order.save(update_fields=['order_status', 'updated_at'])
    from .audit_helpers import audit_order_status

    audit_order_status(
        order=order,
        actor=actor,
        summary=f'完成基础订单 {order.get_display_order_no()}',
    )
    return True, '订单已完成'


def confirm_basic_order_cash(order: BuyOrder, *, actor) -> tuple[bool, str]:
    """确认基础下单现金已收（只改支付状态，不回退履约进度）。"""
    if not basic_order_can_confirm_cash(order):
        return False, '该订单不是待确认的现金单'
    from .audit_helpers import audit_order_status
    from .payments.core import mark_payment_received

    newly = mark_payment_received(order, 'cash')
    if not newly:
        return False, '该订单已收款，无需重复确认'
    audit_order_status(
        order=order,
        actor=actor,
        summary=f'确认现金收款 {order.get_display_order_no()}',
    )
    update_fields = sync_order_desk_progress(order)
    if update_fields:
        order.save(update_fields=list(dict.fromkeys(update_fields)))
    return True, '已确认收款'


def format_order_dish_summary(dish_items, max_len: int = 120) -> str:
    """订单列表用：鱼香肉丝×2、米饭×1"""
    parts = []
    for item in dish_items or []:
        name = (item.get('name') or '商品').strip()
        qty = int(item.get('quantity', 0) or 0)
        if qty <= 0 or not name:
            continue
        parts.append(f'{name}×{qty}')
    if not parts:
        return ''
    text = '、'.join(parts)
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - 1)] + '…'


def build_order_desk_context(seller_id: str, *, work_user, sort_mode: str = 'newest') -> dict:
    """组装通用订单台页面数据。"""
    from .staff_account_helpers import (
        PERM_FULFILLMENT_CASH_MANAGE,
        PERM_ORDERS_CONFIRM_PAYMENT,
        PERM_ORDERS_CONTACT,
        PERM_ORDERS_UPDATE_STATUS,
        PERM_ORDERS_VIEW,
        staff_has_permission,
    )

    can_view = staff_has_permission(work_user, PERM_ORDERS_VIEW)
    can_update = staff_has_permission(work_user, PERM_ORDERS_UPDATE_STATUS)
    can_confirm = staff_has_permission(work_user, PERM_ORDERS_CONFIRM_PAYMENT)
    can_contact = staff_has_permission(work_user, PERM_ORDERS_CONTACT)
    can_cash_manage = staff_has_permission(work_user, PERM_FULFILLMENT_CASH_MANAGE)

    from .workbench_sort_helpers import order_queryset_by_created

    orders = list(
        order_queryset_by_created(
            BuyOrder.objects.filter(
                seller_id=seller_id,
                fulfillment_type='order',
                order_status__in=ACTIVE_BASIC_STATUSES,
            ),
            sort_mode,
        )[:50]
    )

    rows = []
    for order in orders:
        persist_basic_dish_items_if_needed(order)
        total, prepared = count_basic_processed_units(order)
        _, served = count_basic_delivered_units(order)
        rows.append({
            'order': order,
            'item_rows': build_order_desk_item_rows(order),
            'can_mark_all_processed': can_update and basic_order_can_mark_all_processed(order),
            'can_mark_all_delivered': can_update and basic_order_can_mark_all_delivered(order),
            'can_confirm_cash': can_confirm and basic_order_can_confirm_cash(order),
            'needs_cash_before_complete': (
                served >= total
                and total > 0
                and order.payment_method == 'cash'
                and order.payment_status == 'pending_payment'
            ),
            'processed_summary': f'{prepared}/{total}' if total > 0 else '',
            'delivered_summary': f'{served}/{total}' if total > 0 else '',
        })

    cash_exceptions = []
    pending_remittances = []
    if can_cash_manage:
        cash_exceptions = list(
            BuyOrder.objects.filter(
                seller_id=seller_id,
                cash_shortfall_status__in=(
                    'buyer_pending', 'buyer_rejected', 'exception',
                ),
            ).select_related('delivery_order').order_by('updated_at')[:30]
        )
        from .rider_cash_helpers import pending_remittance_requests

        pending_remittances = list(pending_remittance_requests(seller_id)[:30])

    return {
        'order_desk_rows': rows,
        'order_desk_can_view': can_view,
        'order_desk_can_update': can_update,
        'order_desk_can_confirm': can_confirm,
        'order_desk_can_contact': can_contact,
        'order_desk_empty': not rows,
        'cash_manage_allowed': can_cash_manage,
        'cash_exception_orders': cash_exceptions,
        'pending_cash_remittances': pending_remittances,
    }
