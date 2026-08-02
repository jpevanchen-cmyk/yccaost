# 入金申请邮件通知：配送员发起交款申请后提醒有权限的管理人员
#
# 双轨与 new_order 一致：老板轨（卖家后台）+ 值班轨（店铺工作台）。

from __future__ import annotations

import logging

from django.db import transaction

from .email_helpers import parse_recipient_list, send_yecao_mail
from .email_rate_limit_helpers import KIND_REMITTANCE_REQUEST

logger = logging.getLogger('waimai')


def _build_remittance_email(remit) -> tuple[str, str]:
    """拼入金申请提醒邮件标题与正文。"""
    rider = (getattr(remit, 'rider_id', '') or '').strip() or '（未知）'
    count = getattr(remit, 'order_count', 0) or 0
    amount = getattr(remit, 'total_amount', '') or ''
    note = (getattr(remit, 'note', '') or '').strip()

    subject = f'入金申请提醒 · {rider} · {count} 单'
    lines = [
        '您的店铺收到一张配送员交款申请，请尽快核对：',
        f'配送员：{rider}',
        f'订单数：{count}',
        f'金额：¥{amount}',
    ]
    if note:
        lines.append(f'说明：{note}')
    lines.append('')
    lines.append('请到店铺工作台「订单」或卖家后台「支付设置」核对并确认入金。')
    return subject, '\n'.join(lines)


def _collect_remittance_notify_recipients(op) -> list[str]:
    """老板轨 + 值班轨；同一邮箱只发一次。"""
    tracks = (
        (getattr(op, 'boss_remittance_notify_enabled', False), getattr(op, 'boss_remittance_notify_email', '')),
        (getattr(op, 'duty_remittance_notify_enabled', False), getattr(op, 'duty_remittance_notify_email', '')),
    )
    seen: set[str] = set()
    recipients: list[str] = []
    for enabled, raw in tracks:
        if not enabled:
            continue
        for addr in parse_recipient_list(raw or ''):
            key = addr.lower()
            if key in seen:
                continue
            seen.add(key)
            recipients.append(addr)
    return recipients


def notify_remittance_request(remit) -> None:
    """条件满足时给店铺配置的邮箱发入金申请提醒。"""
    from .email_helpers import is_email_ready

    if remit is None or getattr(remit, 'status', '') != 'pending':
        return
    if not is_email_ready():
        return
    try:
        from .operating_helpers import get_operating_settings

        op = get_operating_settings(remit.seller_id)
    except Exception:
        return
    recipients = _collect_remittance_notify_recipients(op)
    if not recipients:
        return

    subject, body = _build_remittance_email(remit)
    send_yecao_mail(
        subject=subject,
        message=body,
        recipient_list=recipients,
        kind=KIND_REMITTANCE_REQUEST,
        dedupe_key=f'remit:{remit.request_id}:pending',
    )


def maybe_notify_remittance_request(remit) -> None:
    """事务提交后调用，避免拖慢骑手提交。"""
    if remit is None:
        return
    try:
        transaction.on_commit(lambda: notify_remittance_request(remit))
    except Exception:
        logger.exception('登记入金申请通知失败')
