# 员工工作台订单排序公共规则。

SORT_NEWEST = 'newest'
SORT_OLDEST = 'oldest'
SESSION_KEY = 'yc_workbench_order_sort'


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
