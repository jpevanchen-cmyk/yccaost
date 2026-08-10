# 服务员工作台 POST 处理

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect

from .models import BuyOrder
from .dispatch_helpers import manual_dispatch_order, reassign_delivery_rider
from .payments import confirm_cash_payment, close_uncollected_cash_order, initiate_payment
from .waiter_helpers import (
    mark_all_dish_served,
    mark_dish_unit_served,
    undo_dish_unit_served,
)
from .workbench_panel_helpers import respond_workbench_action


def _finish_waiter(request, target, *, ok: bool, message: str):
    return respond_workbench_action(request, target, ok=ok, message=message)


def handle_waiter_post(request, seller_id: str, *, redirect_to=None):
    """服务员：按份标记、撤回、确认现金收款"""
    from django.urls import reverse

    operator = getattr(request, 'shop_work_user', None) or request.user
    target = redirect_to or reverse('waiter_home')
    from .staff_account_helpers import PERM_DINING_WAITER, staff_has_permission

    if not staff_has_permission(operator, PERM_DINING_WAITER):
        return _finish_waiter(
            request, target, ok=False, message='您没有服务员工作台操作权限',
        )

    if 'waiter_open_table' in request.POST:
        table_id = request.POST.get('table_id', '').strip()
        from .plugins.dining.waiter_table_helpers import waiter_open_table_for_guest
        from .plugins.dining.waiter_table_order_helpers import build_waiter_table_order_path
        from .shop_work_auth import SESSION_SHOP_WORK_CODE

        ok, msg = waiter_open_table_for_guest(
            seller_id,
            table_id,
            operator=operator,
        )
        if ok:
            shop_code = (request.session.get(SESSION_SHOP_WORK_CODE) or '').strip()
            if shop_code:
                return redirect(build_waiter_table_order_path(shop_code, table_id))
        return _finish_waiter(request, target, ok=ok, message=msg)

    if 'waiter_close_table' in request.POST:
        table_id = request.POST.get('table_id', '').strip()
        from .plugins.dining.waiter_table_helpers import waiter_close_table

        ok, msg = waiter_close_table(
            seller_id,
            table_id,
            operator=operator,
        )
        return _finish_waiter(request, target, ok=ok, message=msg)

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
        return _finish_waiter(request, target, ok=ok, message=msg)

    if 'undo_dish_unit' in request.POST:
        order_id = request.POST.get('order_id', '').strip()
        dish_id = request.POST.get('dish_id', '').strip()
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        ok, msg = undo_dish_unit_served(
            order, dish_id, operator_username=operator.username,
        )
        return _finish_waiter(request, target, ok=ok, message=msg)

    if 'mark_all_served' in request.POST:
        order_id = request.POST.get('order_id', '').strip()
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        ok, msg = mark_all_dish_served(order, operator_username=operator.username)
        return _finish_waiter(request, target, ok=ok, message=msg)

    if 'confirm_cash' in request.POST:
        order_id = request.POST.get('order_id', '').strip()
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        from .waiter_helpers import waiter_can_confirm_cash

        if not waiter_can_confirm_cash(order):
            return _finish_waiter(
                request,
                target,
                ok=False,
                message='这笔订单无需在此确认现金（外卖现金由配送员送达时收取）',
            )
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
        return _finish_waiter(request, target, ok=ok, message=msg)

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
        return _finish_waiter(request, target, ok=ok, message=msg)

    if 'complete_pickup' in request.POST:
        order_id = request.POST.get('order_id', '').strip()
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        from .waiter_helpers import sync_waiter_service_status, waiter_can_complete_in_store

        fields = sync_waiter_service_status(order)
        if fields:
            order.save(update_fields=list(dict.fromkeys(fields)))
        order.refresh_from_db()

        if order.order_status == 'completed':
            if order.is_basic_order():
                msg = '订单已完成'
            elif order.is_dine_in():
                msg = '堂食订单已完成'
            else:
                msg = '打包自取订单已完成'
            return _finish_waiter(request, target, ok=True, message=msg)

        if order.is_basic_order():
            from .order_desk_helpers import complete_basic_order

            if order.is_cash_receipt_pending():
                return _finish_waiter(
                    request, target, ok=False, message='尚未收款，请先确认已收款或无法收款结单',
                )
            if order.payment_status != 'paid':
                return _finish_waiter(
                    request, target, ok=False, message='请先处理收款状态再结束订单',
                )
            if not waiter_can_complete_in_store(order):
                return _finish_waiter(request, target, ok=False, message='当前订单状态不能完成')
            ok, msg = complete_basic_order(order, actor=operator)
            return _finish_waiter(request, target, ok=ok, message=msg)

        if not order.is_in_store():
            return _finish_waiter(request, target, ok=False, message='当前订单状态不能完成')
        if order.is_cash_receipt_pending():
            return _finish_waiter(
                request, target, ok=False, message='尚未收款，请先确认已收款或无法收款结单',
            )
        if order.payment_status != 'paid':
            return _finish_waiter(
                request, target, ok=False, message='请先处理收款状态再结束订单',
            )
        if not waiter_can_complete_in_store(order):
            return _finish_waiter(request, target, ok=False, message='当前订单状态不能完成')

        from .order_status_event_helpers import (
            EVENT_MANUAL_COMPLETE,
            handle_order_status_event,
        )

        fields = handle_order_status_event(
            order,
            EVENT_MANUAL_COMPLETE,
            source='waiter_handlers.complete_order',
        )
        if fields:
            order.save(update_fields=list(dict.fromkeys(fields)))
        if order.order_status != 'completed':
            return _finish_waiter(request, target, ok=False, message='当前订单状态不能完成')
        from .audit_helpers import audit_order_status

        audit_order_status(
            order=order,
            actor=operator,
            summary=f'完成订单 {order.get_display_order_no()}（{order.get_order_status_display()}）',
            request=request,
        )
        if order.is_dine_in():
            msg = '堂食订单已完成'
        else:
            msg = '打包自取订单已完成'
        return _finish_waiter(request, target, ok=True, message=msg)

    if 'dispatch_order' in request.POST:
        order_id = request.POST.get('order_id', '').strip()
        rider_id = request.POST.get('rider_id', '').strip() or None
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        delivery, err = manual_dispatch_order(operator, 'waiter', order, rider_id)
        if delivery:
            return _finish_waiter(
                request, target, ok=True, message=f'已派单给配送员 {delivery.rider_id}',
            )
        return _finish_waiter(request, target, ok=False, message=err or '派单失败')

    if 'reassign_rider' in request.POST:
        from .dispatch_helpers import operator_can_manual_dispatch

        if not operator_can_manual_dispatch(operator, seller_id, 'waiter'):
            return _finish_waiter(
                request, target, ok=False, message='当前店铺设置下，您没有手动派单权限',
            )
        order_id = request.POST.get('order_id', '').strip()
        rider_id = request.POST.get('rider_id', '').strip()
        order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
        ok, msg = reassign_delivery_rider(order, rider_id)
        return _finish_waiter(request, target, ok=ok, message=msg)

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
