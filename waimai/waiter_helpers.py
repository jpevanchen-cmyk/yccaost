# 服务员工作台：订单可见范围、按份标记、状态汇总（A.11.8 补强）

from __future__ import annotations

from django.db import models

from .dispatch_helpers import get_delivery_handoff_mode
from .models import BuyOrder, OrderWaiterDishServeLog, User
from .order_progress_helpers import (
    build_progress_groups,
    count_progress_units,
    find_markable_line,
    find_undo_line,
    norm_dish_id,
    normalize_dish_items as normalize_dish_items_base,
)
from .time_helpers import format_beijing_time

WAITER_STATUS_PENDING = 'pending_serve'
WAITER_STATUS_SERVED = 'served'
WAITER_STATUS_SETTLED = 'settled'

WAITER_SERVICE_STATUS_CHOICES = (
    (WAITER_STATUS_PENDING, '服务中'),
    (WAITER_STATUS_SERVED, '已全部送达'),
    (WAITER_STATUS_SETTLED, '已结账'),
)

# 骑手已取餐后，外卖单不再出现在服务员台
_DELIVERY_DONE_STATUSES = ('picked_up', 'in_transit', 'completed', 'cancelled')


def get_shop_waiters(seller_id: str, *, active_only: bool = False):
    """本店服务员子账号列表"""
    from .staff_account_helpers import PERM_DINING_WAITER, staff_permission_query

    qs = User.objects.filter(
        staff_permission_query(PERM_DINING_WAITER),
        employer_seller_id=seller_id,
    )
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by('date_joined')


def validate_shop_waiter(seller_id: str, username: str) -> bool:
    """确认服务员属于该店铺且账号有效"""
    return get_shop_waiters(seller_id, active_only=True).filter(username=username).exists()


def ensure_waiter_employer(user) -> str | None:
    """服务员所属店铺 ID；无效则 None"""
    from .staff_account_helpers import PERM_DINING_WAITER, staff_has_permission

    if not user.is_authenticated or not staff_has_permission(user, PERM_DINING_WAITER):
        return None
    return (user.employer_seller_id or '').strip() or None


def _norm_dish_id(dish_id: str) -> str:
    return norm_dish_id(dish_id)


def normalize_dish_items(dish_items: list | None) -> tuple[list[dict], bool]:
    """补齐 line_id、served_count 字段"""
    return normalize_dish_items_base(dish_items, ('served_count', 'prepared_count'))


def count_order_units(dish_items: list | None) -> tuple[int, int]:
    """返回 (总份数, 已服务份数)"""
    return count_progress_units(dish_items, 'served_count')


def build_dish_groups(dish_items: list | None) -> list[dict]:
    """
    按菜品 ID 合并展示（不同价档合并为一组），统计总份数与已服务份数。
    """
    return build_progress_groups(dish_items, 'served_count', 'served_qty')


def get_serve_unit_label(order: BuyOrder) -> str:
    """按履约方式返回「每件/每份」动作文案（读工作台壳）"""
    from .workbench_shell_helpers import serve_unit_label_for_order

    return serve_unit_label_for_order(order)


def get_waiter_phase_label(order: BuyOrder) -> str:
    """服务员看到的订单阶段说明（用语跟工作台壳走）"""
    from .workbench_shell_helpers import build_workbench_shell

    shell = build_workbench_shell(order.seller_id)
    rider_w = shell['rider_role_word']
    kitchen_w = shell['kitchen_role_word']
    waiter_w = shell['tab_waiter']
    prep_w = shell['prep_word']
    pickup_w = shell['pickup_word']
    serve_all = shell['serve_dine_in'] if order.is_dine_in() else '交付'

    delivery = getattr(order, 'delivery_order', None)
    total, served = count_order_units(order.dish_items)
    items, _ = normalize_dish_items(order.dish_items)
    prepared = sum(int(i.get('prepared_count') or 0) for i in items)
    handoff_mode = get_delivery_handoff_mode(order.seller_id)
    if order.order_status == 'cancelled' or order.payment_status == 'cancelled':
        return '已取消'
    if total > 0 and served >= total:
        if order.payment_status == 'paid' and order.is_in_store():
            return f'已全部{serve_all} · 已收款'
        if order.payment_status != 'paid':
            return '已全部送达 · 待收款'
        if delivery and delivery.delivery_status == 'accepted':
            return f'已全部交{rider_w} · 待{rider_w} {delivery.rider_id} {pickup_w}'
    if order.payment_status == 'pending_payment' and order.order_status == 'awaiting_payment':
        return '新订单 · 待客人支付'
    if order.is_awaiting_in_store_order_confirm():
        return '待店家备货'
    if order.payment_status == 'paid' and order.order_status == 'awaiting_prep':
        return '已支付 · 待开始备货'
    if order.order_status == 'preparing':
        if served > 0 and served < total:
            return f'{prep_w}/服务中 · 已{get_serve_unit_label(order)} {served}/{total}'
        return f'{kitchen_w}备货中'
    if order.fulfillment_type == 'delivery' and delivery:
        if delivery.delivery_status == 'waiting':
            return f'待派{rider_w}'
        if delivery.delivery_status == 'accepted':
            if handoff_mode == 'kitchen':
                return f'{kitchen_w}直交{rider_w} · {rider_w} {delivery.rider_id}'
            if prepared < total:
                return (
                    f'{kitchen_w}{prep_w}中 · 待{waiter_w}接单'
                    f'（已备好 {prepared}/{total}）'
                )
            if served >= total and total > 0:
                return f'待{rider_w}{pickup_w} · {rider_w} {delivery.rider_id}'
            return f'待交给{rider_w} · {rider_w} {delivery.rider_id}'
    if total > 0 and served < total:
        return f'服务中 · 已{get_serve_unit_label(order)} {served}/{total}'
    if order.payment_status == 'paid':
        return '已收款'
    return order.get_order_status_display()


def query_waiter_active_orders(seller_id: str, *, sort_mode: str = 'newest'):
    """
    服务员可见订单：下单后直至完结。
    外卖单在骑手取餐后从列表消失。
    """
    qs = (
        BuyOrder.objects.filter(seller_id=seller_id)
        .exclude(order_status__in=('cancelled', 'completed'))
        .select_related('delivery_order')
    )
    if get_delivery_handoff_mode(seller_id) == 'kitchen':
        qs = qs.exclude(fulfillment_type='delivery')
    # 外卖：骑手已取走则不再跟踪
    qs = qs.exclude(
        fulfillment_type='delivery',
        delivery_order__delivery_status__in=_DELIVERY_DONE_STATUSES,
    )
    from .workbench_sort_helpers import order_queryset_by_created

    return order_queryset_by_created(qs, sort_mode)


def _find_markable_line(items: list[dict], dish_id: str) -> dict | None:
    """找还可 +1 的一份所在明细行"""
    return find_markable_line(items, dish_id, 'served_count')


def _find_undo_line(items: list[dict], dish_id: str) -> dict | None:
    """找可 -1 的一份所在明细行（从后往前）"""
    return find_undo_line(items, dish_id, 'served_count')


def sync_waiter_service_status(order: BuyOrder) -> list[str]:
    """根据按份进度刷新整单前台状态；返回需 save 的字段名"""
    total, served = count_order_units(order.dish_items)
    update_fields: list[str] = []
    if total == 0:
        new_status = ''
    elif served >= total:
        new_status = WAITER_STATUS_SERVED
    elif served > 0:
        new_status = WAITER_STATUS_PENDING
    else:
        new_status = ''

    if (order.waiter_service_status or '') != new_status:
        order.waiter_service_status = new_status
        update_fields.append('waiter_service_status')

    if (
        order.payment_status == 'paid'
        and served >= total
        and total > 0
        and order.is_in_store()
        and order.order_status in ('awaiting_prep', 'preparing', 'ready_pickup')
    ):
        order.order_status = 'completed'
        order.waiter_service_status = WAITER_STATUS_SETTLED
        update_fields.extend(['order_status', 'waiter_service_status'])
        # 堂食结账完成 → 翻台：关掉桌台会话（游客本机随即看不见）
        from .guest_order_helpers import maybe_close_table_session_after_settle
        maybe_close_table_session_after_settle(order)

    if update_fields:
        update_fields.append('updated_at')
    return update_fields


def mark_dish_unit_served(
    order: BuyOrder,
    dish_id: str,
    *,
    operator_username: str,
) -> tuple[bool, str]:
    """标记某道菜再上一份/交一份"""
    items, struct_changed = normalize_dish_items(order.dish_items)
    if order.fulfillment_type == 'delivery' and get_delivery_handoff_mode(order.seller_id) == 'waiter':
        target = _norm_dish_id(dish_id)
        prepared_total = 0
        served_total = 0
        for row in items:
            if _norm_dish_id(str(row.get('dish_id', ''))) != target:
                continue
            prepared_total += int(row.get('prepared_count') or 0)
            served_total += int(row.get('served_count') or 0)
        if prepared_total <= served_total:
            return False, '后厨尚未备好这一份，暂不能交给骑手'
    line = _find_markable_line(items, dish_id)
    if not line:
        return False, '该菜品已全部标记，无需重复操作'

    line['served_count'] = int(line.get('served_count') or 0) + 1
    order.dish_items = items

    groups = build_dish_groups(items)
    group = next((g for g in groups if g['dish_id'] == _norm_dish_id(dish_id)), None)
    served_after = group['served_qty'] if group else 0
    total_qty = group['total_qty'] if group else 0
    dish_name = group['name'] if group else line.get('name', '菜品')

    OrderWaiterDishServeLog.objects.create(
        order=order,
        dish_id=_norm_dish_id(dish_id),
        dish_name=dish_name,
        line_id=line.get('line_id', ''),
        action=OrderWaiterDishServeLog.ACTION_MARK,
        served_after=served_after,
        total_qty=total_qty,
        changed_by=operator_username,
    )

    update_fields = ['dish_items', 'updated_at']
    if struct_changed:
        pass
    update_fields.extend(sync_waiter_service_status(order))
    order.save(update_fields=list(dict.fromkeys(update_fields)))

    label = get_serve_unit_label(order)
    return True, f'「{dish_name}」已标记 1 份{label}（{served_after}/{total_qty}）'


def undo_dish_unit_served(
    order: BuyOrder,
    dish_id: str,
    *,
    operator_username: str,
) -> tuple[bool, str]:
    """撤回某道菜最近一份标记"""
    items, _ = normalize_dish_items(order.dish_items)
    line = _find_undo_line(items, dish_id)
    if not line:
        return False, '该菜品尚未标记，无法撤回'

    line['served_count'] = int(line.get('served_count') or 0) - 1
    order.dish_items = items

    groups = build_dish_groups(items)
    group = next((g for g in groups if g['dish_id'] == _norm_dish_id(dish_id)), None)
    served_after = group['served_qty'] if group else 0
    total_qty = group['total_qty'] if group else 0
    dish_name = group['name'] if group else line.get('name', '菜品')

    OrderWaiterDishServeLog.objects.create(
        order=order,
        dish_id=_norm_dish_id(dish_id),
        dish_name=dish_name,
        line_id=line.get('line_id', ''),
        action=OrderWaiterDishServeLog.ACTION_UNDO,
        served_after=served_after,
        total_qty=total_qty,
        changed_by=operator_username,
    )

    update_fields = ['dish_items', 'updated_at']
    update_fields.extend(sync_waiter_service_status(order))
    order.save(update_fields=list(dict.fromkeys(update_fields)))

    label = get_serve_unit_label(order)
    return True, f'已撤回「{dish_name}」1 份{label}（现为 {served_after}/{total_qty}）'


def init_waiter_status_on_ready(order: BuyOrder) -> bool:
    """卖家标记出餐时：若尚无按份记录，保持兼容（不再强制写整单待出餐）"""
    return False


def all_dishes_served(order: BuyOrder) -> bool:
    total, served = count_order_units(order.dish_items)
    return total > 0 and served >= total


def waiter_can_collect_payment(order: BuyOrder) -> bool:
    """是否应在服务员台展示「选支付方式 / 扫码收款」入口"""
    if order.payment_status != 'pending_payment':
        return False
    # 已选现金：改走「确认已收现金」按钮
    if order.payment_method == 'cash':
        return False
    return True


def waiter_can_confirm_cash(order: BuyOrder) -> bool:
    """现金单是否可点「确认已收款」。
    只对堂食/打包（到店付）开放：这类是服务员当面收钱。
    外卖货到付款的现金由配送员送达时收取，服务员这里不再出现该按钮。
    """
    if order.payment_method != 'cash' or order.payment_status != 'pending_payment':
        return False
    if order.is_awaiting_in_store_order_confirm():
        return False
    if order.is_in_store():
        return order.order_status in ('awaiting_prep', 'preparing', 'ready_pickup', 'completed')
    return False


def waiter_can_complete_in_store(order: BuyOrder) -> bool:
    """服务员/店主可在工作台完成堂食/打包单"""
    return bool(order.can_complete_in_store_order)


def waiter_can_close_uncollected(order: BuyOrder) -> bool:
    """无法收款时，由工作台直接结单并留原因"""
    return bool(order.can_close_as_uncollected)


def delivery_handoff_ready(order: BuyOrder) -> bool:
    """骑手是否已经可以取餐"""
    if order.fulfillment_type != 'delivery':
        return True
    handoff_mode = get_delivery_handoff_mode(order.seller_id)
    if handoff_mode == 'kitchen':
        items, _ = normalize_dish_items(order.dish_items)
        total = sum(int(i['quantity']) for i in items)
        prepared = sum(int(i.get('prepared_count') or 0) for i in items)
        return total > 0 and prepared >= total
    total, served = count_order_units(order.dish_items)
    return total > 0 and served >= total


def recent_waiter_activity_logs(order: BuyOrder, limit: int = 8) -> list[str]:
    """最近服务员操作记录（按份 + 整单），供页面展示"""
    lines: list[str] = []
    dish_logs = order.waiter_dish_serve_logs.order_by('-changed_at')[:limit]
    for log in dish_logs:
        action = '标记' if log.action == OrderWaiterDishServeLog.ACTION_MARK else '撤回'
        ts = format_beijing_time(log.changed_at, '%H:%M')
        lines.append(
            f'{ts} · {log.changed_by} · {action}「{log.dish_name}」'
            f'（{log.served_after}/{log.total_qty}）'
        )
    if len(lines) < limit:
        status_logs = order.waiter_status_logs.order_by('-changed_at')[: limit - len(lines)]
        labels = dict(WAITER_SERVICE_STATUS_CHOICES)
        for log in status_logs:
            ts = format_beijing_time(log.changed_at, '%H:%M')
            old_l = labels.get(log.from_status, '—') if log.from_status else '—'
            new_l = labels.get(log.to_status, log.to_status)
            lines.append(f'{ts} · {log.changed_by} · {old_l} → {new_l}')
    return lines[:limit]


def persist_dish_items_if_needed(order: BuyOrder) -> None:
    """旧订单首次展示时补齐结构并落库"""
    items, changed = normalize_dish_items(order.dish_items)
    if changed:
        order.dish_items = items
        order.save(update_fields=['dish_items', 'updated_at'])
