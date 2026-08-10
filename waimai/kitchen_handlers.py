from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from .time_helpers import now_local_wall

from .forms import CreateKitchenForm
from .models import BuyOrder
from .dispatch_helpers import (
    manual_dispatch_order,
    maybe_auto_dispatch_order,
    operator_can_manual_dispatch,
    reassign_delivery_rider,
)
from .kitchen_helpers import (
    kitchen_order_can_start,
    mark_all_kitchen_prepared,
    mark_kitchen_dish_unit_prepared,
    undo_kitchen_dish_unit_prepared,
)
from .workbench_panel_helpers import respond_workbench_action


def _finish_kitchen(request, target, *, ok: bool, message: str):
    return respond_workbench_action(request, target, ok=ok, message=message)


def handle_seller_kitchen_post(request, seller_id: str, *, section='kitchen'):
    """卖家管理后厨子账号"""
    if 'create_kitchen' in request.POST:
        form = CreateKitchenForm(request.POST, seller_id=seller_id)
        if form.is_valid():
            form.save()
            messages.success(request, '后厨账号已创建')
        else:
            messages.error(request, '创建失败，请检查用户名和密码')
        return redirect('seller_panel_section', section=section)

    if 'toggle_kitchen' in request.POST:
        from .staff_account_helpers import handle_seller_staff_toggle_post

        return handle_seller_staff_toggle_post(request, seller_id, 'kitchen', section=section)

    return None


def handle_kitchen_board_post(request, seller_id: str, *, redirect_to=None):
    """后厨看板：按份备好/撤回，并负责开始备货"""
    from django.urls import reverse

    operator = getattr(request, 'shop_work_user', None) or request.user
    target = redirect_to or reverse('kitchen_home')
    from .staff_account_helpers import PERM_DINING_KITCHEN, staff_has_permission

    if not staff_has_permission(operator, PERM_DINING_KITCHEN):
        return _finish_kitchen(
            request, target, ok=False, message='您没有后厨工作台操作权限',
        )
    order_id = request.POST.get('order_id', '').strip()
    if not order_id:
        return None
    order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)

    if 'adjust_wait_time' in request.POST:
        from .workbench_action_helpers import handle_adjust_wait_time_action

        return handle_adjust_wait_time_action(request, order, operator, target)

    if 'mark_prepared_unit' in request.POST:
        dish_id = request.POST.get('dish_id', '').strip()
        ok, msg = mark_kitchen_dish_unit_prepared(order, dish_id, operator_username=operator.username)
        return _finish_kitchen(request, target, ok=ok, message=msg)

    if 'undo_prepared_unit' in request.POST:
        dish_id = request.POST.get('dish_id', '').strip()
        ok, msg = undo_kitchen_dish_unit_prepared(order, dish_id, operator_username=operator.username)
        return _finish_kitchen(request, target, ok=ok, message=msg)

    if 'mark_all_prepared' in request.POST:
        ok, msg = mark_all_kitchen_prepared(order, operator_username=operator.username)
        return _finish_kitchen(request, target, ok=ok, message=msg)

    if 'start_preparing' in request.POST:
        if not kitchen_order_can_start(order):
            return _finish_kitchen(request, target, ok=False, message='当前订单不能开始备货')
        from .order_status_transition_helpers import transition_order_status

        transition_order_status(
            order, 'preparing', source='kitchen_handlers.start_preparing',
        )
        order.preparing_at = now_local_wall()
        update_fields = ['order_status', 'preparing_at', 'updated_at']
        if not order.estimated_ready_at:
            from .wait_time_helpers import assign_default_wait_time

            assign_default_wait_time(order, at=order.preparing_at, save=False)
            update_fields.append('estimated_ready_at')
        order.save(update_fields=update_fields)
        from .audit_helpers import audit_order_status

        audit_order_status(
            order=order,
            actor=operator,
            summary=f'开始备货 {order.get_display_order_no()}',
            request=request,
        )
        msg = '后厨已开始备货'
        delivery, err = maybe_auto_dispatch_order(order)
        if delivery:
            msg += f'；已自动派单给骑手 {delivery.rider_id}'
        elif err:
            msg += f'；自动派单未成功：{err}'
        return _finish_kitchen(request, target, ok=True, message=msg)

    if 'dispatch_order' in request.POST:
        rider_id = request.POST.get('rider_id', '').strip() or None
        delivery, err = manual_dispatch_order(operator, 'kitchen', order, rider_id)
        if delivery:
            return _finish_kitchen(
                request, target, ok=True, message=f'已派单给配送员 {delivery.rider_id}',
            )
        return _finish_kitchen(request, target, ok=False, message=err or '派单失败')

    if 'reassign_rider' in request.POST:
        if not operator_can_manual_dispatch(operator, seller_id, 'kitchen'):
            return _finish_kitchen(
                request, target, ok=False, message='当前店铺设置下，您没有手动派单权限',
            )
        rider_id = request.POST.get('rider_id', '').strip()
        ok, msg = reassign_delivery_rider(order, rider_id)
        return _finish_kitchen(request, target, ok=ok, message=msg)

    from .panel_refresh_helpers import is_panel_refresh, panel_refresh_fail

    if is_panel_refresh(request):
        return panel_refresh_fail('未能识别后厨操作，请刷新页面后重试')

    return None
