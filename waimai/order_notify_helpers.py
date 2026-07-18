# 新订单邮件通知：有新订单时给店铺配置的收件邮箱发提醒
#
# 说明：
# - 只有服务器已在 .env 配好发信邮箱（YECAO_EMAIL_READY 为真），且店铺开启了通知、
#   填了收件邮箱时才会真的发信；否则安静跳过，不报错、不卡顿。
# - 发信放在数据库事务提交后进行，避免拖慢下单本身。

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

logger = logging.getLogger('waimai')


def _parse_recipients(raw: str) -> list[str]:
    """把「a@x.com, b@y.com」这类字符串拆成邮箱列表"""
    if not raw:
        return []
    text = raw.replace('；', ',').replace(';', ',').replace(' ', ',')
    return [e.strip() for e in text.split(',') if e.strip()]


def _build_new_order_email(order) -> tuple[str, str]:
    """拼一封新订单提醒邮件的标题与正文（尽量健壮，字段缺失也不报错）"""
    try:
        order_no = order.get_display_order_no()
    except Exception:
        order_no = str(getattr(order, 'order_id', ''))
    try:
        channel = order.get_fulfillment_display_short()
    except Exception:
        channel = getattr(order, 'fulfillment_type', '') or ''
    amount = getattr(order, 'total_amount', '') or ''
    note = (getattr(order, 'buyer_note', '') or '').strip()

    subject = f'新订单提醒 · {order_no}（{channel}）'
    lines = [
        '您的店铺有一笔新订单：',
        f'订单号：{order_no}',
        f'类型：{channel}',
        f'金额：¥{amount}',
    ]
    if note:
        lines.append(f'买家备注：{note}')
    lines.append('')
    lines.append('请到店铺工作台查看并处理。')
    return subject, '\n'.join(lines)


def notify_new_order(order) -> None:
    """给店铺配置的收件邮箱发一封新订单提醒（条件不满足时安静跳过）"""
    if not getattr(settings, 'YECAO_EMAIL_READY', False):
        return
    try:
        from .operating_helpers import get_operating_settings

        op = get_operating_settings(order.seller_id)
    except Exception:
        return
    if not getattr(op, 'order_notify_enabled', False):
        return
    recipients = _parse_recipients(getattr(op, 'order_notify_email', '') or '')
    if not recipients:
        return

    subject, body = _build_new_order_email(order)
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None) or recipients[0],
            recipient_list=recipients,
            fail_silently=True,
        )
    except Exception:
        logger.exception('新订单通知邮件发送失败')


def on_buy_order_created(sender, instance, created, **kwargs):
    """BuyOrder 新建后触发：提交事务后再发邮件，避免拖慢下单"""
    if not created:
        return
    try:
        transaction.on_commit(lambda: notify_new_order(instance))
    except Exception:
        logger.exception('登记新订单通知失败')
