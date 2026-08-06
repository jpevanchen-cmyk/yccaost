# 选支付方式幂等（进度 80 · 幂等第 7 步）
# 买家支付页 pay_order、服务员协助收款 waiter_pay_order 共用

from __future__ import annotations

from django.http import HttpRequest

from .models import BuyOrder


def _resolve_initiate_payment_actor(request: HttpRequest, order: BuyOrder) -> str:
    """同一操作者 + 同一订单隔离幂等键。"""
    if getattr(request.user, 'is_authenticated', False):
        return str(request.user.pk)
    buyer = (order.buyer_id or '').strip()
    if buyer:
        return f'buyer:{buyer}'[:32]
    return (request.session.session_key or 'anon')[:32]


def run_initiate_payment_idempotent(request: HttpRequest, order: BuyOrder, execute):
    """
    选支付方式写操作幂等：同一 scope+键只执行一次 initiate_payment，
    重复请求返回首次 HTTP 响应（含整页跳转）。
    """
    from .idempotency_helpers import idempotency_scope, run_idempotent

    actor = _resolve_initiate_payment_actor(request, order)
    scope = idempotency_scope('initiate_payment', str(order.order_id), actor)
    return run_idempotent(request, scope, execute)
