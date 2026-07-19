# 工作台跨页签公共动作：避免服务员、后厨各写一套。


def handle_adjust_wait_time_action(request, order, operator, target):
    """统一处理“修改本单预计时间”；不是该动作时返回 None。"""
    if 'adjust_wait_time' not in request.POST:
        return None

    from django.contrib import messages
    from django.shortcuts import redirect

    from .audit_helpers import audit_order_status
    from .wait_time_helpers import adjust_order_wait_time

    ok, msg, minutes = adjust_order_wait_time(order, request.POST.get('wait_minutes'))
    if ok:
        audit_order_status(
            order=order,
            actor=operator,
            summary=f'调整预计时间 {order.get_display_order_no()}（从现在起约 {minutes} 分钟）',
            request=request,
        )
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return redirect(target)
