from django.db.models import Q
from django.utils import timezone

from .models import BuyOrder, OrderKitchenDishPrepLog, User
from .operating_helpers import get_operating_settings
from .order_progress_helpers import (
    build_progress_groups,
    count_progress_units,
    find_markable_line,
    find_undo_line,
    norm_dish_id,
    normalize_dish_items,
)
from .time_helpers import format_beijing_time


def get_shop_kitchens(seller_id: str, *, active_only: bool = False):
    """本店后厨子账号列表"""
    qs = User.objects.filter(role='kitchen', employer_seller_id=seller_id)
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by('date_joined')


def ensure_kitchen_employer(user) -> str | None:
    """后厨所属店铺 ID；无效则 None"""
    if not user.is_authenticated or user.role != 'kitchen' or not user.is_active:
        return None
    return (user.employer_seller_id or '').strip() or None


def query_kitchen_board_orders(seller_id: str):
    """
    后厨看板可见订单：
    - 已支付待备货
    - 备货中
    - 已备好但尚未被客人/骑手取走
    """
    return (
        BuyOrder.objects.filter(
            seller_id=seller_id,
            payment_status='paid',
        )
        .filter(
            Q(order_status__in=('awaiting_prep', 'preparing', 'ready_pickup'))
            | Q(fulfillment_type='delivery', delivery_order__delivery_status='accepted')
        )
        .exclude(order_status='completed')
        .select_related('delivery_order')
        .order_by('created_at')
    )


def get_delivery_handoff_mode(seller_id: str) -> str:
    """外卖交接方式：默认服务员交骑手"""
    settings = get_operating_settings(seller_id)
    return (settings.delivery_handoff_mode or 'waiter').strip() or 'waiter'


def build_kitchen_dish_groups(order: BuyOrder) -> list[dict]:
    """后厨按份备好分组统计"""
    return build_progress_groups(order.dish_items, 'prepared_count', 'prepared_qty')


def count_kitchen_units(order: BuyOrder) -> tuple[int, int]:
    """后厨总份数 / 已备好份数"""
    return count_progress_units(order.dish_items, 'prepared_count')


def build_kitchen_phase_label(order: BuyOrder) -> str:
    """后厨看板上的阶段说明"""
    total, prepared = count_kitchen_units(order)
    handoff_mode = get_delivery_handoff_mode(order.seller_id)
    if order.order_status == 'awaiting_prep':
        return '新单待备货'
    if order.order_status == 'preparing':
        if prepared > 0 and prepared < total:
            return f'备货中 · 已备好 {prepared}/{total}'
        return '备货中'
    if order.fulfillment_type == 'delivery' and getattr(order, 'delivery_order', None):
        if handoff_mode == 'waiter':
            return '已备好 · 待服务员交骑手'
        rider_id = order.delivery_order.rider_id
        return f'已备好 · 待骑手 {rider_id} 取餐'
    if order.is_dine_in():
        return '已出餐 · 待服务员上桌'
    if order.is_takeaway():
        return '已备好 · 待买家自取'
    return order.get_order_status_display()


def build_kitchen_dish_rows(order: BuyOrder) -> list[dict]:
    """后厨每单菜品明细；备注用显眼字段占位"""
    rows = []
    groups = build_kitchen_dish_groups(order)
    for item in groups:
        rows.append({
            'dish_id': item.get('dish_id', ''),
            'name': item.get('name', '菜品'),
            'quantity': int(item.get('total_qty', 0) or 0),
            'prepared_qty': int(item.get('prepared_qty', 0) or 0),
            'note': (order.buyer_note or '').strip(),
        })
    return rows


def build_kitchen_summary(orders: list[BuyOrder]) -> list[dict]:
    """待备菜品汇总：只统计还没备好的份数"""
    merged: dict[str, dict] = {}
    for order in orders:
        if order.order_status not in ('awaiting_prep', 'preparing'):
            continue
        for item in build_kitchen_dish_groups(order):
            remain = int(item.get('total_qty', 0) or 0) - int(item.get('prepared_qty', 0) or 0)
            if remain <= 0:
                continue
            name = item.get('name', '菜品')
            if name not in merged:
                merged[name] = {'name': name, 'quantity': 0}
            merged[name]['quantity'] += remain
    return sorted(merged.values(), key=lambda x: (-x['quantity'], x['name']))


def latest_kitchen_new_order_ts(orders: list[BuyOrder]) -> int:
    """给前端提示音用：最新新单时间戳（毫秒）"""
    new_orders = [o for o in orders if o.order_status == 'awaiting_prep']
    if not new_orders:
        return 0
    latest = max(o.created_at for o in new_orders if o.created_at)
    return int(latest.timestamp() * 1000) if latest else 0


def sync_kitchen_progress(order: BuyOrder) -> list[str]:
    """按备好份数刷新整单状态"""
    total, prepared = count_kitchen_units(order)
    if total <= 0:
        return []
    if prepared < total:
        if order.order_status in ('awaiting_prep', 'ready_pickup'):
            order.order_status = 'preparing'
            return ['order_status', 'updated_at']
        return []
    if order.order_status in ('awaiting_prep', 'preparing'):
        order.order_status = 'ready_pickup'
        order.ready_at = timezone.now()
        return ['order_status', 'ready_at', 'updated_at']
    return []


def mark_kitchen_dish_unit_prepared(order: BuyOrder, dish_id: str, *, operator_username: str) -> tuple[bool, str]:
    """后厨标记某道菜再备好一份"""
    items, _ = normalize_dish_items(order.dish_items, ('prepared_count', 'served_count'))
    line = find_markable_line(items, dish_id, 'prepared_count')
    if not line:
        return False, '该菜品已全部标记备好，无需重复操作'

    line['prepared_count'] = int(line.get('prepared_count') or 0) + 1
    order.dish_items = items
    groups = build_progress_groups(items, 'prepared_count', 'prepared_qty')
    group = next((g for g in groups if g['dish_id'] == norm_dish_id(dish_id)), None)
    prepared_after = group['prepared_qty'] if group else 0
    total_qty = group['total_qty'] if group else 0
    dish_name = group['name'] if group else line.get('name', '菜品')

    OrderKitchenDishPrepLog.objects.create(
        order=order,
        dish_id=norm_dish_id(dish_id),
        dish_name=dish_name,
        line_id=line.get('line_id', ''),
        action=OrderKitchenDishPrepLog.ACTION_MARK,
        prepared_after=prepared_after,
        total_qty=total_qty,
        changed_by=operator_username,
    )
    update_fields = ['dish_items', 'updated_at']
    update_fields.extend(sync_kitchen_progress(order))
    order.save(update_fields=list(dict.fromkeys(update_fields)))
    return True, f'「{dish_name}」已标记 1 份备好（{prepared_after}/{total_qty}）'


def undo_kitchen_dish_unit_prepared(order: BuyOrder, dish_id: str, *, operator_username: str) -> tuple[bool, str]:
    """后厨撤回某道菜最近一份备好"""
    items, _ = normalize_dish_items(order.dish_items, ('prepared_count', 'served_count'))
    line = find_undo_line(items, dish_id, 'prepared_count')
    if not line:
        return False, '该菜品尚未标记备好，无法撤回'

    line['prepared_count'] = int(line.get('prepared_count') or 0) - 1
    order.dish_items = items
    groups = build_progress_groups(items, 'prepared_count', 'prepared_qty')
    group = next((g for g in groups if g['dish_id'] == norm_dish_id(dish_id)), None)
    prepared_after = group['prepared_qty'] if group else 0
    total_qty = group['total_qty'] if group else 0
    dish_name = group['name'] if group else line.get('name', '菜品')

    OrderKitchenDishPrepLog.objects.create(
        order=order,
        dish_id=norm_dish_id(dish_id),
        dish_name=dish_name,
        line_id=line.get('line_id', ''),
        action=OrderKitchenDishPrepLog.ACTION_UNDO,
        prepared_after=prepared_after,
        total_qty=total_qty,
        changed_by=operator_username,
    )
    update_fields = ['dish_items', 'updated_at']
    update_fields.extend(sync_kitchen_progress(order))
    order.save(update_fields=list(dict.fromkeys(update_fields)))
    return True, f'已撤回「{dish_name}」1 份备好（现为 {prepared_after}/{total_qty}）'


def recent_kitchen_activity_logs(order: BuyOrder, limit: int = 8) -> list[str]:
    """最近后厨操作记录"""
    lines: list[str] = []
    for log in order.kitchen_dish_prep_logs.order_by('-changed_at')[:limit]:
        action = '标记' if log.action == OrderKitchenDishPrepLog.ACTION_MARK else '撤回'
        ts = format_beijing_time(log.changed_at, '%H:%M')
        lines.append(f'{ts} · {log.changed_by} · {action}「{log.dish_name}」（{log.prepared_after}/{log.total_qty}）')
    return lines
