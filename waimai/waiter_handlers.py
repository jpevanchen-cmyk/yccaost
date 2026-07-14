# 服务员工作台 POST 处理

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone

from .models import BuyOrder
from .dispatch_helpers import dispatch_buy_order, validate_shop_rider
from .payments import confirm_cash_payment, confirm_in_store_order, close_uncollected_cash_order, initiate_payment
from .waiter_helpers import (
    get_delivery_handoff_mode,
    mark_dish_unit_served,
    undo_dish_unit_served,
)


def handle_waiter_post(request, seller_id: str, *, redirect_to=None):
    """服务员：按份标记、撤回、确认现金收款"""
    from django.urls import reverse

    operator = getattr(request, 'shop_work_user', None) or request.user
    target = redirect_to or reverse('waiter_home')
    can_dispatch = operator.role == 'seller' or get_delivery_handoff_mode(seller_id) == 'waiter'
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

    if 'confirm_in_store_order' in request.POST:
        order_id = request.POST.get('order_id', '').strip()
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        try:
            eta = int(request.POST.get('eta_minutes', '20'))
        except (TypeError, ValueError):
            eta = 20
        ok, msg = confirm_in_store_order(order, eta)
        if ok:
            from .audit_helpers import audit_order_status
            audit_order_status(
                order=order,
                actor=operator,
                summary=f'确认到店单 {order.get_display_order_no()}（预计 {eta} 分钟）',
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
        if not can_dispatch:
            messages.error(request, '当前店铺设置下，服务员没有手动派单权限')
            return redirect(target)
        order_id = request.POST.get('order_id', '').strip()
        rider_id = request.POST.get('rider_id', '').strip() or None
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        if order.payment_status == 'paid' and order.order_status in ('awaiting_prep', 'preparing', 'ready_pickup'):
            delivery, err = dispatch_buy_order(order, rider_id=rider_id)
            if delivery:
                messages.success(request, f'已派单给骑手 {delivery.rider_id}')
            else:
                messages.error(request, err or '派单失败')
        else:
            messages.error(request, '当前订单状态不能派单')
        return redirect(target)

    if 'reassign_rider' in request.POST:
        if not can_dispatch:
            messages.error(request, '当前店铺设置下，服务员没有手动派单权限')
            return redirect(target)
        order_id = request.POST.get('order_id', '').strip()
        rider_id = request.POST.get('rider_id', '').strip()
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        if hasattr(order, 'delivery_order') and rider_id:
            if not validate_shop_rider(seller_id, rider_id):
                messages.error(request, '只能改派给本店当前上班中的骑手')
            else:
                delivery = order.delivery_order
                if delivery.delivery_status == 'accepted':
                    delivery.rider_id = rider_id
                    delivery.save(update_fields=['rider_id', 'updated_at'])
                    messages.success(request, f'已改派给骑手 {rider_id}')
                else:
                    messages.error(request, '配送已开始，无法改派')
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
