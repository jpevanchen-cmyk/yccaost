# 80-2d：现金管理 · 交款确认 / 异常处理 POST

from django.shortcuts import get_object_or_404

from .cash_manage_panel_helpers import respond_cash_manage_action


def handle_cash_management_post(request, seller_id: str, operator, *, redirect_to: str):
    """管理人员处理现金异常与配送员交款申请。"""
    from .staff_account_helpers import (
        PERM_FULFILLMENT_CASH_MANAGE,
        staff_has_permission,
    )

    action = (request.POST.get('cash_manage_action') or '').strip()
    if not action:
        return None
    if not staff_has_permission(operator, PERM_FULFILLMENT_CASH_MANAGE):
        return respond_cash_manage_action(
            request, redirect_to, ok=False, message='您没有现金异常与入金处理权限',
        )

    if action == 'approve_exception':
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
        return respond_cash_manage_action(request, redirect_to, ok=ok, message=msg)

    if action in ('confirm_remittance', 'reject_remittance'):
        from .rider_cash_helpers import review_cash_remittance_request

        ok, msg = review_cash_remittance_request(
            seller_id,
            request.POST.get('request_id'),
            operator.username,
            approve=(action == 'confirm_remittance'),
            note=request.POST.get('review_note', ''),
        )
        return respond_cash_manage_action(request, redirect_to, ok=ok, message=msg)
    return None
