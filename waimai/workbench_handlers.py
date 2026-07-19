# 员工工作台管理 + 店铺工作台 POST

from django.contrib import messages
from django.shortcuts import redirect

from .forms import ShopWorkbenchSettingsForm
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
    from .shop_work_helpers import build_shop_work_redirect
    from .staff_account_helpers import handle_staff_work_status_post
    from .waiter_handlers import handle_waiter_post

    operator = work_user or getattr(request, 'shop_work_user', None)
    if operator is None:
        messages.error(request, '请先登录店铺工作台')
        return redirect(build_shop_work_redirect(shop_code, current_view))

    redirect_to = build_shop_work_redirect(shop_code, current_view)
    response = handle_staff_work_status_post(request, operator, redirect_to=redirect_to)
    if response:
        return response

    # 临时把操作人挂到 request，供现有 handler 读取
    request.shop_work_user = operator

    if current_view == 'orders':
        response = handle_cash_management_post(
            request, seller_id, operator, redirect_to=redirect_to,
        )
        if response:
            return response
        from .order_desk_handlers import handle_order_desk_post

        response = handle_order_desk_post(
            request, seller_id, redirect_to=redirect_to, work_user=operator,
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

    messages.error(request, '您没有权限执行此操作')
    return redirect(redirect_to)


def handle_cash_management_post(request, seller_id: str, operator, *, redirect_to: str):
    """订单台：管理人员处理现金异常与配送员交款申请。"""
    from .staff_account_helpers import (
        PERM_FULFILLMENT_CASH_MANAGE,
        staff_has_permission,
    )

    action = (request.POST.get('cash_manage_action') or '').strip()
    if not action:
        return None
    if not staff_has_permission(operator, PERM_FULFILLMENT_CASH_MANAGE):
        messages.error(request, '您没有现金异常与入金处理权限')
        return redirect(redirect_to)

    if action == 'approve_exception':
        from django.shortcuts import get_object_or_404

        from .models import BuyOrder
        from .payments import manager_approve_cash_exception

        order = get_object_or_404(
            BuyOrder.objects.select_related('delivery_order'),
            order_id=request.POST.get('order_id'),
            seller_id=seller_id,
        )
        ok, msg = manager_approve_cash_exception(
            order, operator.username, request.POST.get('decision_note', ''),
        )
        if ok:
            from .audit_helpers import audit_order_status

            audit_order_status(
                order=order,
                actor=operator,
                summary=f'管理人员兜底处理现金异常 {order.get_display_order_no()}',
                request=request,
            )
            from .dispatch_helpers import maybe_refill_dispatch_after_rider_available
            from .models import User

            rider = User.objects.filter(
                username=order.delivery_order.rider_id,
                employer_seller_id=seller_id,
            ).first()
            if rider:
                maybe_refill_dispatch_after_rider_available(rider)
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(redirect_to)

    if action in ('confirm_remittance', 'reject_remittance'):
        from .rider_cash_helpers import review_cash_remittance_request

        ok, msg = review_cash_remittance_request(
            seller_id,
            request.POST.get('request_id'),
            operator.username,
            approve=(action == 'confirm_remittance'),
            note=request.POST.get('review_note', ''),
        )
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(redirect_to)
    return None


def handle_my_deliveries_post(request, *, seller_id: str, shop_code: str, user, redirect_to: str | None = None):
    """骑手 Tab：取餐 / 送达"""
    from django.shortcuts import get_object_or_404, redirect
    from django.utils import timezone

    from .models import DeliveryOrder
    from .shop_work_helpers import build_shop_work_redirect
    from .waiter_helpers import delivery_handoff_ready

    rider_id = user.username
    seller_mode = user.role == 'seller'
    fallback = redirect_to or build_shop_work_redirect(shop_code, 'rider')

    if request.method != 'POST':
        return None
    from .staff_account_helpers import PERM_DINING_RIDER, staff_has_permission

    if not staff_has_permission(user, PERM_DINING_RIDER):
        messages.error(request, '您没有配送工作台操作权限')
        return redirect(fallback)

    delivery_id = request.POST.get('delivery_id')
    action = request.POST.get('action')
    if action == 'request_remittance':
        if seller_mode:
            messages.error(request, '店主不能代配送员发起交款申请')
            return redirect(fallback)
        from .rider_cash_helpers import create_cash_remittance_request

        remit, msg = create_cash_remittance_request(
            seller_id, rider_id, request.POST.get('remittance_note', ''),
        )
        if remit:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(fallback)
    if action == 'claim_pending':
        if seller_mode:
            messages.error(request, '店主只能查看待派单池，请使用配送员账号接单')
            return redirect(fallback)
        from .dispatch_helpers import try_dispatch_pending_for_rider

        delivery, err = try_dispatch_pending_for_rider(
            seller_id,
            rider_id,
            order_id=(request.POST.get('order_id') or '').strip(),
        )
        if delivery:
            messages.success(request, f'接单成功：{delivery.buy_order.get_display_order_no()}')
        else:
            messages.error(request, err or '当前没有可接的订单')
        return redirect(fallback)

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
            if not delivery_handoff_ready(order.buy_order):
                short_id = str(delivery_id).replace('-', '')[:8] if delivery_id else ''
                if short_id:
                    return redirect(f'{fallback}#delivery-{short_id}')
                return redirect(fallback)
            order.delivery_status = 'picked_up'
            order.picked_up_at = timezone.now()
            order.save()
            order.buy_order.order_status = 'delivering'
            order.buy_order.save(update_fields=['order_status', 'updated_at'])
            from .audit_helpers import audit_order_status
            audit_order_status(
                order=order.buy_order,
                actor=user,
                summary=f'骑手取餐 {order.buy_order.get_display_order_no()}',
                request=request,
            )
        elif action == 'collect_cash':
            # 外卖货到付款：骑手送达时收现金，记录实收金额
            if order.delivery_status != 'picked_up':
                messages.error(request, '请先完成取餐，面对买家时再登记实收金额')
            else:
                from .payments import rider_collect_cash
                ok, msg = rider_collect_cash(
                    order.buy_order,
                    user.username,
                    request.POST.get('cash_amount', ''),
                    request.POST.get('shortfall_reason', ''),
                )
                if ok:
                    order.buy_order.refresh_from_db()
                    messages.success(request, msg)
                    from .audit_helpers import audit_order_status
                    audit_order_status(
                        order=order.buy_order,
                        actor=user,
                        summary=f'骑手收款 {order.buy_order.get_display_order_no()} · ¥{order.buy_order.cash_collected_amount}',
                        request=request,
                    )
                else:
                    messages.error(request, msg)
        elif action == 'mark_cash_exception':
            if order.delivery_status != 'picked_up':
                messages.error(request, '尚未取餐，当前不能标记当面收款异常')
            else:
                from .payments import mark_cash_exception

                ok, msg = mark_cash_exception(
                    order.buy_order, user.username, request.POST.get('exception_note', ''),
                )
                if ok:
                    messages.success(request, msg)
                    from .audit_helpers import audit_order_status

                    audit_order_status(
                        order=order.buy_order,
                        actor=user,
                        summary=f'标记现金异常 {order.buy_order.get_display_order_no()}',
                        request=request,
                    )
                else:
                    messages.error(request, msg)
        elif action == 'complete' and order.delivery_status == 'picked_up':
            # 货到付款单：未收款不许结单（须先收现金或顾客已扫码付）
            if order.buy_order.is_cod_awaiting_collection():
                messages.error(request, '这是货到付款单，请先确认收到现金（或顾客已扫码付款）再点已送达')
                short_id = str(delivery_id).replace('-', '')[:8] if delivery_id else ''
                if short_id:
                    return redirect(f'{fallback}#delivery-{short_id}')
                return redirect(fallback)
            order.delivery_status = 'completed'
            order.completed_at = timezone.now()
            order.save()
            order.buy_order.order_status = 'completed'
            order.buy_order.save(update_fields=['order_status', 'updated_at'])
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
                    messages.success(
                        request,
                        f'已自动补派下一单：{next_delivery.buy_order.get_display_order_no()}',
                    )
    except DeliveryOrder.DoesNotExist:
        pass

    short_id = str(delivery_id).replace('-', '')[:8] if delivery_id else ''
    if short_id:
        return redirect(f'{fallback}#delivery-{short_id}')
    return redirect(fallback)
