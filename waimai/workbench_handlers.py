# 员工工作台管理 + 店铺工作台 POST

from django.contrib import messages
from django.shortcuts import redirect

from .forms import ShopWorkbenchSettingsForm, ShopDutyOrderNotifyForm, ShopDutyRemittanceNotifyForm
from .operating_helpers import get_operating_settings


def handle_seller_workbench_post(request, seller_id: str):
    """卖家后台：员工工作台管理（账号、协作设置）"""
    from .staff_account_helpers import (
        AttendanceFilterForm,
        export_attendance_csv,
        handle_create_staff_account_post,
        handle_edit_staff_account_post,
        handle_manager_staff_status_post,
        handle_staff_cancel_perm_post,
        handle_toggle_staff_account_post,
        purge_old_attendance_logs,
        query_attendance_logs,
    )

    if 'save_workbench_settings' in request.POST:
        operating = get_operating_settings(seller_id)
        form = ShopWorkbenchSettingsForm(request.POST, request.FILES, instance=operating)
        from .plugins.fulfillment.ownership import fulfillment_plugin_enabled
        if not fulfillment_plugin_enabled(seller_id):
            for fname in ('delivery_handoff_mode', 'auto_dispatch_enabled'):
                form.fields.pop(fname, None)
        if form.is_valid():
            form.save()
            purge_old_attendance_logs(seller_id, form.cleaned_data.get('attendance_retention_days'))
            messages.success(request, '工作台协作设置已保存')
        else:
            messages.error(request, '设置无效，请检查输入')
        return redirect('seller_panel_section', section='workbench')

    response = handle_manager_staff_status_post(request, seller_id, section='workbench')
    if response:
        return response

    response = handle_staff_cancel_perm_post(request, seller_id, section='workbench')
    if response:
        return response

    response = handle_create_staff_account_post(request, seller_id, section='workbench')
    if response:
        return response

    response = handle_edit_staff_account_post(request, seller_id, section='workbench')
    if response:
        return response

    response = handle_toggle_staff_account_post(request, seller_id, section='workbench')
    if response:
        return response

    if 'export_attendance_csv' in request.POST:
        operating = get_operating_settings(seller_id)
        filter_form = AttendanceFilterForm(request.POST, seller_id=seller_id)
        filters = filter_form.cleaned_data if filter_form.is_valid() else {}
        logs = query_attendance_logs(seller_id, operating.attendance_retention_days, filters=filters)
        return export_attendance_csv(logs, seller_id=seller_id)

    return None


def handle_shop_work_post(request, seller_id: str, shop_code: str, current_view: str, perms: dict, *, work_user=None):
    """店铺工作台内表单提交（按当前 Tab 与权限分发）"""
    from .kitchen_handlers import handle_kitchen_board_post
    from .shop_work_helpers import build_shop_work_path, build_shop_work_redirect
    from .staff_account_helpers import handle_staff_work_status_post
    from .waiter_handlers import handle_waiter_post

    operator = work_user or getattr(request, 'shop_work_user', None)
    if operator is None:
        messages.error(request, '请先登录店铺工作台')
        return redirect(build_shop_work_redirect(shop_code, current_view))

    # H3 · 值班防漏单邮件：仅店主可改
    if 'save_duty_order_notify' in request.POST:
        if operator.role != 'seller':
            messages.error(request, '只有店主可以修改值班防漏单邮件设置')
            return redirect(build_shop_work_redirect(shop_code, current_view))
        operating = get_operating_settings(seller_id)
        form = ShopDutyOrderNotifyForm(request.POST, instance=operating)
        if form.is_valid():
            form.save()
            messages.success(request, '值班防漏单邮件已保存')
        else:
            messages.error(request, '设置无效，请检查邮箱格式')
        return redirect(build_shop_work_redirect(shop_code, current_view))

    # 值班入金申请邮件：仅店主可改
    if 'save_duty_remittance_notify' in request.POST:
        if operator.role != 'seller':
            messages.error(request, '只有店主可以修改值班入金申请邮件设置')
            return redirect(build_shop_work_redirect(shop_code, current_view))
        operating = get_operating_settings(seller_id)
        form = ShopDutyRemittanceNotifyForm(request.POST, instance=operating)
        if form.is_valid():
            form.save()
            messages.success(request, '值班入金申请邮件已保存')
        else:
            messages.error(request, '设置无效，请检查邮箱格式')
        return redirect(build_shop_work_redirect(shop_code, current_view))

    redirect_to = build_shop_work_redirect(shop_code, current_view)
    from .workbench_sort_helpers import resolve_workbench_sort

    sort_mode = resolve_workbench_sort(request)
    form_action = build_shop_work_path(shop_code, view=current_view)
    form_action = f'{form_action}&sort={sort_mode}'
    from .workbench_panel_helpers import attach_shop_work_panel_ctx

    from .staff_account_helpers import PERM_DINING_RIDER, staff_has_permission

    attach_shop_work_panel_ctx(
        request,
        seller_id=seller_id,
        shop_code=shop_code,
        view=current_view,
        work_user=operator,
        sort_mode=sort_mode,
        form_action=form_action,
        redirect_to=redirect_to,
        can_operate_kitchen=bool(perms.get('kitchen')),
        can_operate_waiter=bool(perms.get('waiter')),
        can_operate_cashier=bool(perms.get('cashier')),
        can_operate_rider=bool(perms.get('rider')),
        show_rider_extras=staff_has_permission(operator, PERM_DINING_RIDER),
    )

    response = handle_staff_work_status_post(request, operator, redirect_to=redirect_to)
    if response:
        return response

    # 临时把操作人挂到 request，供现有 handler 读取
    request.shop_work_user = operator

    if current_view == 'orders':
        from .order_desk_handlers import handle_order_desk_post

        response = handle_order_desk_post(
            request, seller_id, redirect_to=redirect_to, work_user=operator,
        )
        if response:
            return response

    if current_view == 'cash_manage' and perms.get('cash_manage'):
        from .cash_manage_handlers import handle_cash_management_post

        response = handle_cash_management_post(
            request, seller_id, operator, redirect_to=redirect_to,
        )
        if response:
            return response

    if current_view == 'waiter' and perms.get('waiter'):
        response = handle_waiter_post(request, seller_id, redirect_to=redirect_to)
        if response:
            return response

    if current_view == 'kitchen' and perms.get('kitchen'):
        response = handle_kitchen_board_post(request, seller_id, redirect_to=redirect_to)
        if response:
            return response

    if current_view == 'rider' and perms.get('rider'):
        response = handle_my_deliveries_post(
            request,
            seller_id=seller_id,
            shop_code=shop_code,
            user=operator,
        )
        if response:
            return response

    if current_view == 'cashier' and perms.get('cashier'):
        from .cashier_handlers import handle_cashier_post

        response = handle_cashier_post(
            request, seller_id, shop_code, redirect_to=redirect_to, work_user=operator,
        )
        if response:
            return response

    messages.error(request, '您没有权限执行此操作')
    return redirect(redirect_to)


def handle_my_deliveries_post(request, *, seller_id: str, shop_code: str, user, redirect_to: str | None = None):
    """骑手 Tab：取餐 / 送达 / 货到付款登记"""
    from django.shortcuts import redirect

    from .models import DeliveryOrder
    from .shop_work_helpers import build_shop_work_redirect
    from .workbench_panel_helpers import respond_workbench_action

    def _finish(*, ok: bool, message: str, delivery_id=None):
        extra = None
        if delivery_id:
            short_id = str(delivery_id).replace('-', '')[:8]
            extra = {'scroll_to': f'delivery-{short_id}'}
        return respond_workbench_action(
            request,
            fallback,
            ok=ok,
            message=message,
            extra=extra,
        )

    rider_id = user.username
    seller_mode = user.role == 'seller'
    fallback = redirect_to or build_shop_work_redirect(shop_code, 'rider')

    if request.method != 'POST':
        return None
    from .staff_account_helpers import PERM_DINING_RIDER, staff_has_permission

    if not staff_has_permission(user, PERM_DINING_RIDER):
        return _finish(ok=False, message='您没有配送工作台操作权限')

    delivery_id = request.POST.get('delivery_id')
    action = request.POST.get('action')
    if action == 'request_remittance':
        if seller_mode:
            return _finish(ok=False, message='店主不能代配送员发起交款申请')
        from .rider_cash_helpers import create_cash_remittance_request

        remit, msg = create_cash_remittance_request(
            seller_id, rider_id, request.POST.get('remittance_note', ''),
        )
        return _finish(ok=bool(remit), message=msg)
    if action == 'claim_pending':
        if seller_mode:
            return _finish(ok=False, message='店主只能查看待派单池，请使用配送员账号接单')
        from .dispatch_helpers import try_dispatch_pending_for_rider

        delivery, err = try_dispatch_pending_for_rider(
            seller_id,
            rider_id,
            order_id=(request.POST.get('order_id') or '').strip(),
        )
        if delivery:
            return _finish(ok=True, message=f'接单成功：{delivery.buy_order.get_display_order_no()}')
        return _finish(ok=False, message=err or '当前没有可接的订单')

    try:
        if seller_mode:
            order = DeliveryOrder.objects.select_related('buy_order').get(
                delivery_id=delivery_id,
                buy_order__seller_id=seller_id,
            )
        else:
            order = DeliveryOrder.objects.select_related('buy_order').get(
                delivery_id=delivery_id, rider_id=rider_id,
            )
        if action == 'pickup' and order.delivery_status == 'accepted':
            from waimai.plugins.fulfillment.delivery_workflow_helpers import apply_rider_pickup

            ok, msg = apply_rider_pickup(order)
            if ok:
                from .audit_helpers import audit_order_status
                audit_order_status(
                    order=order.buy_order,
                    actor=user,
                    summary=f'骑手取餐 {order.buy_order.get_display_order_no()}',
                    request=request,
                )
            return _finish(ok=ok, message=msg, delivery_id=delivery_id)
        if action == 'start_delivery' and order.delivery_status == 'picked_up':
            from waimai.plugins.fulfillment.delivery_workflow_helpers import apply_rider_start_delivery

            ok, msg = apply_rider_start_delivery(order)
            if ok:
                from .audit_helpers import audit_order_status
                audit_order_status(
                    order=order.buy_order,
                    actor=user,
                    summary=f'骑手开始送餐 {order.buy_order.get_display_order_no()}',
                    request=request,
                )
            return _finish(ok=ok, message=msg, delivery_id=delivery_id)
        if action == 'collect_cash':
            from waimai.plugins.fulfillment.delivery_workflow_helpers import RIDER_POST_PICKUP_STATUSES

            if order.delivery_status not in RIDER_POST_PICKUP_STATUSES:
                return _finish(
                    ok=False,
                    message='请先完成取餐，面对买家时再登记实收金额',
                    delivery_id=delivery_id,
                )
            from .payments import rider_collect_cash
            ok, msg = rider_collect_cash(
                order.buy_order,
                user.username,
                request.POST.get('cash_amount', ''),
                request.POST.get('shortfall_reason', ''),
            )
            if ok:
                order.buy_order.refresh_from_db()
                from .audit_helpers import audit_order_status
                audit_order_status(
                    order=order.buy_order,
                    actor=user,
                    summary=(
                        f'骑手收款 {order.buy_order.get_display_order_no()}'
                        f' · ¥{order.buy_order.cash_collected_amount}'
                    ),
                    request=request,
                )
            return _finish(ok=ok, message=msg, delivery_id=delivery_id)
        if action == 'mark_cash_exception':
            from waimai.plugins.fulfillment.delivery_workflow_helpers import RIDER_POST_PICKUP_STATUSES

            if order.delivery_status not in RIDER_POST_PICKUP_STATUSES:
                return _finish(
                    ok=False,
                    message='尚未取餐，当前不能标记当面收款异常',
                    delivery_id=delivery_id,
                )
            from .payments import mark_cash_exception

            ok, msg = mark_cash_exception(
                order.buy_order, user.username, request.POST.get('exception_note', ''),
            )
            if ok:
                from .audit_helpers import audit_order_status

                audit_order_status(
                    order=order.buy_order,
                    actor=user,
                    summary=f'标记现金异常 {order.buy_order.get_display_order_no()}',
                    request=request,
                )
            return _finish(ok=ok, message=msg, delivery_id=delivery_id)
        if action == 'complete' and order.delivery_status in ('in_transit', 'overtime'):
            from waimai.plugins.fulfillment.delivery_workflow_helpers import apply_rider_complete_delivery

            ok, msg = apply_rider_complete_delivery(order)
            if ok:
                from .audit_helpers import audit_order_status
                audit_order_status(
                    order=order.buy_order,
                    actor=user,
                    summary=f'骑手送达完成 {order.buy_order.get_display_order_no()}',
                    request=request,
                )
                if not seller_mode:
                    from .dispatch_helpers import maybe_refill_dispatch_after_rider_available

                    next_delivery, _ = maybe_refill_dispatch_after_rider_available(user)
                    if next_delivery:
                        msg = (
                            f'{msg}；已自动补派下一单：'
                            f'{next_delivery.buy_order.get_display_order_no()}'
                        )
            return _finish(ok=ok, message=msg, delivery_id=delivery_id)
    except DeliveryOrder.DoesNotExist:
        return _finish(ok=False, message='找不到该配送单')

    short_id = str(delivery_id).replace('-', '')[:8] if delivery_id else ''
    if short_id:
        return redirect(f'{fallback}#delivery-{short_id}')
    return redirect(fallback)
