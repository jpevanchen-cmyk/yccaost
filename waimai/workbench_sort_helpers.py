# 员工工作台订单排序公共规则。

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

SORT_NEWEST = 'newest'
SORT_OLDEST = 'oldest'
SESSION_KEY = 'yc_workbench_order_sort'

# 无预计出餐时间时，排序上放到同档最后
_BOARD_ETA_FALLBACK = datetime(9999, 12, 31, tzinfo=dt_timezone.utc)

# 后厨/服务员看板：按履约方式分组的标题与折叠 id
WORK_BOARD_FULFILLMENT_GROUPS = (
    ('delivery', '🛵 外卖', 'delivery'),
    ('takeaway', '🥡 打包自取', 'takeaway'),
    ('dine_in', '🍽 堂食', 'dine-in'),
)


def normalize_workbench_sort(value: str) -> str:
    """只接受两种稳定值，默认新单在上。"""
    return SORT_OLDEST if (value or '').strip() == SORT_OLDEST else SORT_NEWEST


def resolve_workbench_sort(request) -> str:
    """读取并记住本设备选择的排序。"""
    requested = (request.GET.get('sort') or '').strip()
    if requested in (SORT_NEWEST, SORT_OLDEST):
        request.session[SESSION_KEY] = requested
        request.session.modified = True
        return requested
    return normalize_workbench_sort(request.session.get(SESSION_KEY, SORT_NEWEST))


def order_queryset_by_created(queryset, sort_mode: str):
    """所有工作台页签共用的下单时间排序。"""
    field = 'created_at' if normalize_workbench_sort(sort_mode) == SORT_OLDEST else '-created_at'
    return queryset.order_by(field)


def _board_eta_sort_key(estimated_ready_at):
    """预计出餐时间：越早越靠前；未填写则排在本档末尾。"""
    if estimated_ready_at is None:
        return _BOARD_ETA_FALLBACK
    return estimated_ready_at


def sort_kitchen_board_rows(rows: list) -> list:
    """
    后厨看板排序：未全部备好的在上；同档按预计出餐时间从早到晚。
    rows 元素须含 order 键。
    """
    from .kitchen_helpers import count_kitchen_units

    def sort_key(row):
        order = row['order']
        total, prepared = count_kitchen_units(order)
        is_all_prepared = total > 0 and prepared >= total
        return (1 if is_all_prepared else 0, _board_eta_sort_key(order.estimated_ready_at))

    return sorted(rows, key=sort_key)


def sort_waiter_board_rows(rows: list) -> list:
    """
    服务员看板排序：未全部出餐的在上；同档按预计出餐时间从早到晚。
    rows 元素须含 order 键。
    """
    from .waiter_helpers import count_order_units

    def sort_key(row):
        order = row['order']
        total, served = count_order_units(order.dish_items)
        is_all_served = total > 0 and served >= total
        return (1 if is_all_served else 0, _board_eta_sort_key(order.estimated_ready_at))

    return sorted(rows, key=sort_key)


def order_fulfillment_bucket(order) -> str:
    """把订单归到外卖 / 打包 / 堂食分组。"""
    if order.fulfillment_type == 'delivery':
        return 'delivery'
    if order.is_takeaway():
        return 'takeaway'
    if order.is_dine_in():
        return 'dine_in'
    return 'takeaway'


def group_board_rows_by_fulfillment(rows: list, *, fold_id_prefix: str = 'work') -> list[dict]:
    """
    后厨/服务员看板：按履约方式分成可折叠区块。
    fold_id_prefix 用于区分后厨与服务员折叠 id，避免同页冲突。
    """
    buckets = {key: [] for key, _, _ in WORK_BOARD_FULFILLMENT_GROUPS}
    for row in rows:
        bucket = order_fulfillment_bucket(row['order'])
        buckets.setdefault(bucket, []).append(row)

    groups = []
    first_open_assigned = False
    for key, title, fold_suffix in WORK_BOARD_FULFILLMENT_GROUPS:
        group_rows = buckets.get(key, [])
        fold_open = (not first_open_assigned and bool(group_rows))
        if fold_open:
            first_open_assigned = True
        groups.append({
            'key': key,
            'title': title,
            'fold_id': f'{fold_id_prefix}-fold-{fold_suffix}',
            'orders': group_rows,
            'count': len(group_rows),
            'fold_open': fold_open,
        })
    return groups
