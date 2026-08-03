# 实体收银台 Tab：POST 处理

from django.shortcuts import get_object_or_404, redirect

from .cashier_helpers import (
    cashier_can_start_wechat,
    cashier_confirm_payment,
    cashier_confirm_simulate_payment,
)
from .models import BuyOrder
from .workbench_panel_helpers import respond_workbench_action


def _finish_cashier(request, redirect_to, *, ok: bool, message: str):
    """收银台操作：Panel 静默刷新或整页 redirect"""
    return respond_workbench_action(request, redirect_to, ok=ok, message=message)


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
        return _finish_cashier(
            request, redirect_to, ok=False, message='您没有收银台操作权限',
        )

    order = get_object_or_404(
        BuyOrder,
        order_id=request.POST.get('order_id'),
        seller_id=seller_id,
    )

    if action == 'start_wechat':
        from django.urls import reverse

        ok, msg = cashier_can_start_wechat(order, seller_id)
        if not ok:
            return _finish_cashier(request, redirect_to, ok=False, message=msg)
        # 微信扫码页是独立子页，须整页跳转，不走 Panel
        return redirect(
            reverse(
                'shop_work_cashier_wechat',
                kwargs={'shop_code': shop_code, 'order_id': order.order_id},
            )
        )

    if action == 'simulate_pay':
        ok, msg = cashier_confirm_simulate_payment(order, actor=work_user)
        return _finish_cashier(request, redirect_to, ok=ok, message=msg)

    if action != 'collect':
        return _finish_cashier(request, redirect_to, ok=False, message='未知操作')

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
    return _finish_cashier(request, redirect_to, ok=ok, message=msg)
