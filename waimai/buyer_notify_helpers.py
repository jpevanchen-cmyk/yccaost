# 买家邮件通知：订单新留言、货到付款少收待确认

from __future__ import annotations

import logging

from django.db import transaction

from .email_helpers import send_yecao_mail
from .email_rate_limit_helpers import KIND_BUYER_CASH_SHORTFALL, KIND_BUYER_ORDER_MSG
from .models import BuyOrder, User

logger = logging.getLogger('waimai')


def _buyer_recipient(order: BuyOrder) -> str | None:
    buyer_id = (order.buyer_id or '').strip()
    if not buyer_id:
        return None
    user = User.objects.filter(username=buyer_id, role='buyer').first()
    if not user or not getattr(user, 'buyer_notify_enabled', False):
        return None
    email = (getattr(user, 'buyer_notify_email', '') or '').strip()
    if not email:
        return None
    return email


def notify_buyer_order_message(order: BuyOrder, *, preview: str) -> None:
    """店家在订单沟通留言后，通知买家（若买家已开启并填邮箱）"""
    recipient = _buyer_recipient(order)
    if not recipient:
        return
    try:
        order_no = order.get_display_order_no()
    except Exception:
        order_no = str(order.order_id)
    subject = f'订单有新留言 · {order_no}'
    body = (
        f'您在订单 {order_no} 中有新的店家留言：\n\n'
        f'{preview}\n\n'
        '请登录野草系统，在「我的订单 → 订单详情 → 订单沟通」查看并回复。'
    )
    send_yecao_mail(
        subject=subject,
        message=body,
        recipient_list=[recipient],
        kind=KIND_BUYER_ORDER_MSG,
        dedupe_key=f'order:{order.order_id}:shop_msg',
    )


def notify_buyer_cash_shortfall(order: BuyOrder) -> None:
    """配送员登记少收、等待买家确认时发邮件"""
    recipient = _buyer_recipient(order)
    if not recipient:
        return
    try:
        order_no = order.get_display_order_no()
    except Exception:
        order_no = str(order.order_id)
    diff = order.cash_shortfall_amount
    subject = f'请确认货到付款实付金额 · {order_no}'
    body = (
        f'订单 {order_no} 的配送员登记了实付金额，与您应付金额不一致。\n'
        f'应收：¥{order.total_amount}，实付：¥{order.cash_collected_amount}，差额：¥{diff}\n'
        f'原因：{order.cash_shortfall_reason}\n\n'
        '请尽快打开订单详情，在页面上确认或拒绝。确认前配送员不能交餐结单。'
    )
    send_yecao_mail(
        subject=subject,
        message=body,
        recipient_list=[recipient],
        kind=KIND_BUYER_CASH_SHORTFALL,
        dedupe_key=f'order:{order.order_id}:cash_shortfall',
    )


def schedule_buyer_order_message_notify(order: BuyOrder, preview: str) -> None:
    try:
        transaction.on_commit(lambda: notify_buyer_order_message(order, preview=preview))
    except Exception:
        logger.exception('登记买家留言通知失败')


def schedule_buyer_cash_shortfall_notify(order: BuyOrder) -> None:
    try:
        transaction.on_commit(lambda: notify_buyer_cash_shortfall(order))
    except Exception:
        logger.exception('登记买家少收确认通知失败')
