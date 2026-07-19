# 服务员工作台 POST 处理

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect

from .models import BuyOrder
from .dispatch_helpers import manual_dispatch_order, reassign_delivery_rider
from .payments import confirm_cash_payment, close_uncollected_cash_order, initiate_payment
from .waiter_helpers import (
    mark_dish_unit_served,
    undo_dish_unit_served,
)


def handle_waiter_post(request, seller_id: str, *, redirect_to=None):
    """服务员：按份标记、撤回、确认现金收款"""
    from django.urls import reverse

    operator = getattr(request, 'shop_work_user', None) or request.user
    target = redirect_to or reverse('waiter_home')
    from .staff_account_helpers import PERM_DINING_WAITER, staff_has_permission

    if not staff_has_permission(operator, PERM_DINING_WAITER):
        messages.error(request, '您没有服务员工作台操作权限')
        return redirect(target)
    if 'adjust_wait_time' in request.POST:
        order_id = request.POST.get('order_id', '').strip()
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        from .workbench_action_helpers import handle_adjust_wait_time_action

        return handle_adjust_wait_time_action(request, order, operator, target)

    if 'mark_dish_unit' in request.POST:
        order_id = request.POST.get('order_id', '').strip()
        dish_id = request.POST.get('dish_id', '').strip()
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        ok, msg = mark_dish_unit_served(
            order, dish_id, operator_username=operator.username,
        )
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(target)

    if 'undo_dish_unit' in request.POST:
        order_id = request.POST.get('order_id', '').strip()
        dish_id = request.POST.get('dish_id', '').strip()
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        ok, msg = undo_dish_unit_served(
            order, dish_id, operator_username=operator.username,
        )
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(target)

    if 'confirm_cash' in request.POST:
        order_id = request.POST.get('order_id', '').strip()
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        # 防篡改：外卖货到付款不在服务员台确认现金，钱由配送员送达时收
        from .waiter_helpers import waiter_can_confirm_cash
        if not waiter_can_confirm_cash(order):
            messages.error(request, '这笔订单无需在此确认现金（外卖现金由配送员送达时收取）')
            return redirect(target)
        ok, msg = confirm_cash_payment(order)
        if ok:
            from .audit_helpers import audit_order_status
            from .waiter_helpers import sync_waiter_service_status
            fields = sync_waiter_service_status(order)
            if fields:
                order.save(update_fields=fields)
            audit_order_status(
                order=order,
                actor=operator,
                summary=f'确认现金收款 {order.get_display_order_no()}',
                request=request,
            )
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(target)

    if 'close_uncollected' in request.POST:
        order_id = request.POST.get('order_id', '').strip()
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        reason = request.POST.get('cash_uncollected_reason', '')
        ok, msg = close_uncollected_cash_order(order, reason)
        if ok:
            from .audit_helpers import audit_order_status
            audit_order_status(
                order=order,
                actor=operator,
                summary=f'未收款结案 {order.get_display_order_no()}：{reason or "无备注"}',
                request=request,
            )
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(target)

    if 'complete_pickup' in request.POST:
        order_id = request.POST.get('order_id', '').strip()
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        if not order.is_in_store() or order.order_status != 'ready_pickup':
            messages.error(request, '当前订单状态不能完成')
        elif order.is_cash_receipt_pending():
            messages.error(request, '尚未收款，请先确认已收款或无法收款结单')
        elif order.payment_status != 'paid':
            messages.error(request, '请先处理收款状态再结束订单')
        else:
            order.order_status = 'completed'
            order.save(update_fields=['order_status', 'updated_at'])
            from .audit_helpers import audit_order_status
            audit_order_status(
                order=order,
                actor=operator,
                summary=f'完成订单 {order.get_display_order_no()}（{order.get_order_status_display()}）',
                request=request,
            )
            if order.is_dine_in():
                messages.success(request, '堂食订单已完成')
            else:
                messages.success(request, '打包自取订单已完成')
        return redirect(target)

    if 'dispatch_order' in request.POST:
        order_id = request.POST.get('order_id', '').strip()
        rider_id = request.POST.get('rider_id', '').strip() or None
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        delivery, err = manual_dispatch_order(operator, 'waiter', order, rider_id)
        if delivery:
            messages.success(request, f'已派单给配送员 {delivery.rider_id}')
        else:
            messages.error(request, err or '派单失败')
        return redirect(target)

    if 'reassign_rider' in request.POST:
        from .dispatch_helpers import operator_can_manual_dispatch

        if not operator_can_manual_dispatch(operator, seller_id, 'waiter'):
            messages.error(request, '当前店铺设置下，您没有手动派单权限')
            return redirect(target)
        order_id = request.POST.get('order_id', '').strip()
        rider_id = request.POST.get('rider_id', '').strip()
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        ok, msg = reassign_delivery_rider(order, rider_id)
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(target)

    return None


def handle_waiter_pay_post(request, order: BuyOrder, client_ip: str):
    """服务员收款页：选择支付方式"""
    method = request.POST.get('payment_method', '').strip()
    result = initiate_payment(order, method, client_ip)
    return result


def handle_seller_waiter_post(request, seller_id: str, *, section='waiters'):
    """卖家管理服务员子账号"""
    if 'create_waiter' in request.POST:
        from .forms import CreateWaiterForm

        form = CreateWaiterForm(request.POST, seller_id=seller_id)
        if form.is_valid():
            form.save()
            messages.success(request, '服务员账号已创建')
        else:
            messages.error(request, '创建失败，请检查用户名和密码')
        return redirect('seller_panel_section', section=section)

    if 'toggle_waiter' in request.POST:
        from .staff_account_helpers import handle_seller_staff_toggle_post

        return handle_seller_staff_toggle_post(request, seller_id, 'waiter', section=section)

    return None
