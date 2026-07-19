from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone

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
    mark_kitchen_dish_unit_prepared,
    undo_kitchen_dish_unit_prepared,
)


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
        messages.error(request, '您没有后厨工作台操作权限')
        return redirect(target)
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
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(target)

    if 'undo_prepared_unit' in request.POST:
        dish_id = request.POST.get('dish_id', '').strip()
        ok, msg = undo_kitchen_dish_unit_prepared(order, dish_id, operator_username=operator.username)
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(target)

    if 'start_preparing' in request.POST:
        if kitchen_order_can_start(order):
            order.order_status = 'preparing'
            order.preparing_at = timezone.now()
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
            messages.success(request, '后厨已开始备货')
            delivery, err = maybe_auto_dispatch_order(order)
            if delivery:
                messages.success(request, f'已自动派单给骑手 {delivery.rider_id}')
            elif err:
                messages.error(request, err)
        else:
            messages.error(request, '当前订单不能开始备货')
        return redirect(target)

    if 'dispatch_order' in request.POST:
        rider_id = request.POST.get('rider_id', '').strip() or None
        delivery, err = manual_dispatch_order(operator, 'kitchen', order, rider_id)
        if delivery:
            messages.success(request, f'已派单给配送员 {delivery.rider_id}')
        else:
            messages.error(request, err or '派单失败')
        return redirect(target)

    if 'reassign_rider' in request.POST:
        if not operator_can_manual_dispatch(operator, seller_id, 'kitchen'):
            messages.error(request, '当前店铺设置下，您没有手动派单权限')
            return redirect(target)
        rider_id = request.POST.get('rider_id', '').strip()
        ok, msg = reassign_delivery_rider(order, rider_id)
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(target)

    return None
