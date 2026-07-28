# 实体收银台 Tab：POST 处理

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect

from .cashier_helpers import (
    cashier_can_start_wechat,
    cashier_confirm_payment,
    cashier_confirm_simulate_payment,
)
from .models import BuyOrder


def handle_cashier_post(
    request, seller_id: str, shop_code: str, *, redirect_to: str, work_user,
):
    """收银台表单提交。"""
    action = (request.POST.get('cashier_action') or '').strip()
    if not action:
        return None

    from .staff_account_helpers import (
        PERM_FULFILLMENT_CASH_MANAGE,
        PERM_ORDERS_CASHIER,
        staff_has_permission,
    )

    if not staff_has_permission(work_user, PERM_ORDERS_CASHIER):
        messages.error(request, '您没有收银台操作权限')
        return redirect(redirect_to)

    order = get_object_or_404(
        BuyOrder,
        order_id=request.POST.get('order_id'),
        seller_id=seller_id,
    )

    if action == 'start_wechat':
        from django.urls import reverse

        ok, msg = cashier_can_start_wechat(order, seller_id)
        if not ok:
            messages.error(request, msg)
            return redirect(redirect_to)
        return redirect(
            reverse(
                'shop_work_cashier_wechat',
                kwargs={'shop_code': shop_code, 'order_id': order.order_id},
            )
        )

    if action == 'simulate_pay':
        ok, msg = cashier_confirm_simulate_payment(order, actor=work_user)
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(redirect_to)

    if action != 'collect':
        messages.error(request, '未知操作')
        return redirect(redirect_to)

    channel = (request.POST.get('cashier_channel') or '').strip()
    custom = (request.POST.get('cashier_channel_custom') or '').strip()
    if custom:
        channel = custom

    ok, msg = cashier_confirm_payment(
        order,
        actor=work_user,
        pay_mode=(request.POST.get('pay_mode') or '').strip(),
        collected_amount=request.POST.get('collected_amount'),
        channel=channel,
        shortfall_reason=request.POST.get('shortfall_reason', ''),
        can_manage_shortfall=staff_has_permission(work_user, PERM_FULFILLMENT_CASH_MANAGE),
    )
    if ok:
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return redirect(redirect_to)
