# 员工工作台管理 + 店铺工作台 POST

from django.contrib import messages
from django.shortcuts import redirect

from .forms import ShopWorkbenchSettingsForm
from .kitchen_handlers import handle_seller_kitchen_post
from .operating_helpers import get_operating_settings
from .rider_handlers import handle_seller_rider_post
from .waiter_handlers import handle_seller_waiter_post


def handle_seller_workbench_post(request, seller_id: str):
    """卖家后台：员工工作台管理（账号、协作设置）"""
    from .staff_account_helpers import (
        AttendanceFilterForm,
        export_attendance_csv,
        handle_manager_staff_status_post,
        purge_old_attendance_logs,
        query_attendance_logs,
    )

    if 'save_workbench_settings' in request.POST:
        operating = get_operating_settings(seller_id)
        form = ShopWorkbenchSettingsForm(request.POST, instance=operating)
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

    if 'export_attendance_csv' in request.POST:
        operating = get_operating_settings(seller_id)
        filter_form = AttendanceFilterForm(request.POST)
        filters = filter_form.cleaned_data if filter_form.is_valid() else {}
        logs = query_attendance_logs(seller_id, operating.attendance_retention_days, filters=filters)
        return export_attendance_csv(logs, seller_id=seller_id)

    response = handle_seller_waiter_post(request, seller_id, section='workbench')
    if response:
        return response

    response = handle_seller_kitchen_post(request, seller_id, section='workbench')
    if response:
        return response

    response = handle_seller_rider_post(request, seller_id, section='workbench')
    if response:
        return response

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

    delivery_id = request.POST.get('delivery_id')
    action = request.POST.get('action')
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
        elif action == 'complete' and order.delivery_status == 'picked_up':
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
    except DeliveryOrder.DoesNotExist:
        pass

    short_id = str(delivery_id).replace('-', '')[:8] if delivery_id else ''
    if short_id:
        return redirect(f'{fallback}#delivery-{short_id}')
    return redirect(fallback)
