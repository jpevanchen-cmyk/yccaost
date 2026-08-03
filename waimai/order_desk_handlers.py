# 主体通用订单台：工作台表单提交

from django.shortcuts import get_object_or_404

from .models import BuyOrder
from .order_desk_helpers import (
    confirm_basic_order_cash,
    mark_all_basic_items_delivered,
    mark_all_basic_items_processed,
    mark_basic_item_delivered,
    mark_basic_item_processed,
    undo_basic_item_delivered,
    undo_basic_item_processed,
)
from .staff_account_helpers import (
    PERM_ORDERS_CONFIRM_PAYMENT,
    PERM_ORDERS_UPDATE_STATUS,
    staff_has_permission,
)
from .workbench_panel_helpers import respond_workbench_action


def handle_order_desk_post(request, seller_id: str, *, redirect_to: str, work_user):
    """处理通用订单台按钮；无相关动作时返回 None。"""
    order_id = (request.POST.get('order_id') or '').strip()
    if not order_id:
        return None

    action_keys = (
        'order_desk_mark_processed',
        'order_desk_undo_processed',
        'order_desk_mark_delivered',
        'order_desk_undo_delivered',
        'order_desk_mark_all_processed',
        'order_desk_mark_all_delivered',
        'order_desk_confirm_cash',
    )
    if not any(key in request.POST for key in action_keys):
        return None

    order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)

    if 'order_desk_confirm_cash' in request.POST:
        if not staff_has_permission(work_user, PERM_ORDERS_CONFIRM_PAYMENT):
            return respond_workbench_action(
                request, redirect_to, ok=False, message='您没有确认收款的权限',
            )
        ok, msg = confirm_basic_order_cash(order, actor=work_user)
        return respond_workbench_action(request, redirect_to, ok=ok, message=msg)

    if not staff_has_permission(work_user, PERM_ORDERS_UPDATE_STATUS):
        return respond_workbench_action(
            request, redirect_to, ok=False, message='您没有修改订单状态的权限',
        )

    if 'order_desk_mark_all_processed' in request.POST:
        ok, msg = mark_all_basic_items_processed(order, actor=work_user)
    elif 'order_desk_mark_all_delivered' in request.POST:
        ok, msg = mark_all_basic_items_delivered(order, actor=work_user)
    elif 'order_desk_mark_processed' in request.POST:
        dish_id = (request.POST.get('dish_id') or '').strip()
        ok, msg = mark_basic_item_processed(order, dish_id, actor=work_user)
    elif 'order_desk_undo_processed' in request.POST:
        dish_id = (request.POST.get('dish_id') or '').strip()
        ok, msg = undo_basic_item_processed(order, dish_id, actor=work_user)
    elif 'order_desk_mark_delivered' in request.POST:
        dish_id = (request.POST.get('dish_id') or '').strip()
        ok, msg = mark_basic_item_delivered(order, dish_id, actor=work_user)
    else:
        dish_id = (request.POST.get('dish_id') or '').strip()
        ok, msg = undo_basic_item_delivered(order, dish_id, actor=work_user)

    return respond_workbench_action(request, redirect_to, ok=ok, message=msg)
