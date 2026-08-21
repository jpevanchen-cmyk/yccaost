# 游客打包/外卖：订单凭证邮件（填了邮箱才发；无发信配置则安静跳过）
# 时机：与「商家应处理新单」同口径——在线已付，或已选定现金/货到付款（未付纯挂单不发）

from __future__ import annotations

import logging

from django.db import transaction

from waimai.email_helpers import is_email_ready, send_yecao_mail
from waimai.email_rate_limit_helpers import KIND_GUEST_ORDER_VOUCHER
from waimai.models import BuyOrder, ShopProfile
from waimai.order_helpers import dish_items_with_line_totals

logger = logging.getLogger('waimai')


def _build_voucher_email(order: BuyOrder) -> tuple[str, str]:
    """拼订单凭证邮件标题与正文（白话、只含本单事实）。"""
    try:
        order_no = order.get_display_order_no()
    except Exception:
        order_no = str(order.order_id)
    try:
        channel = order.get_fulfillment_display_short()
    except Exception:
        channel = getattr(order, 'fulfillment_type', '') or ''

    shop = ShopProfile.objects.filter(seller_id=order.seller_id).first()
    shop_name = (shop.shop_name if shop else '') or order.seller_id
    shop_addr = (shop.address if shop else '') or '—'

    subject = f'订单凭证 · {shop_name} · {order_no}'
    lines = [
        '这是您在野草系统未登录下单的订单凭证。请自行保存本邮件。',
        '',
        f'订单号：{order_no}',
        f'状态：{order.get_order_status_display()}',
        f'支付：{order.get_payment_status_display()}'
        + (
            f' · {order.get_payment_method_display()}'
            if order.payment_method else ''
        ),
        f'取餐方式：{channel}',
        f'合计：¥{order.total_amount}',
        '',
        f'店铺：{shop_name}',
        f'店铺地址：{shop_addr}',
        '',
        f'顾客姓名：{(order.guest_contact_name or "").strip() or "—"}',
        f'顾客电话：{(order.guest_contact_phone or "").strip() or "—"}',
        f'顾客邮箱：{(order.guest_contact_email or "").strip() or "—"}',
    ]
    if (order.fulfillment_type or '') == 'delivery':
        lines.append(f'送达地址：{(order.delivery_address or "").strip() or "—"}')
    lines.append('')
    lines.append('订单内容：')
    try:
        for item in dish_items_with_line_totals(order.dish_items or []):
            lines.append(
                f'- {item.get("name", "商品")} × {item.get("quantity", 0)}'
                f'　¥{item.get("line_total", "")}'
            )
    except Exception:
        lines.append('- （明细暂无法列出，请以页面凭证为准）')
    if order.delivery_fee:
        lines.append(f'- 配送费　¥{order.delivery_fee}')
    lines.extend([
        '',
        '说明：未登录时请以本邮件或网页凭证截图/打印为准。',
        '到店可出示本邮件，或报订单号与顾客姓名、电话与店家核对。',
        '现金/货到付款：店家已按选定方式接单备货；实际交款按店内流程办理。',
    ])
    return subject, '\n'.join(lines)


def notify_guest_order_voucher(order: BuyOrder) -> bool:
    """
    给游客邮箱发订单凭证。
    条件：游客打包/外卖、填了邮箱、已进入「商家应处理」（在线已付或已选现金/货到付款）、
    且服务器已配置发信。失败安静返回 False。
    """
    from waimai.order_alert_helpers import is_shop_new_order
    from waimai.plugins.dining.guest_order_helpers import is_guest_remote_order

    if not is_guest_remote_order(order):
        return False
    email = (order.guest_contact_email or '').strip()
    if not email:
        return False
    if not is_shop_new_order(order):
        return False
    if not is_email_ready():
        return False

    subject, body = _build_voucher_email(order)
    return send_yecao_mail(
        subject=subject,
        message=body,
        recipient_list=[email],
        kind=KIND_GUEST_ORDER_VOUCHER,
        dedupe_key=f'order:{order.order_id}:guest_voucher',
    )


def schedule_guest_order_voucher_notify(order: BuyOrder) -> None:
    """事务提交后再发，避免拖慢支付/选方式。"""
    order_id = order.order_id

    def _run():
        try:
            latest = BuyOrder.objects.filter(order_id=order_id).first()
            if latest:
                notify_guest_order_voucher(latest)
        except Exception:
            logger.exception('游客订单凭证邮件发送失败 order=%s', order_id)

    try:
        transaction.on_commit(_run)
    except Exception:
        logger.exception('登记游客订单凭证邮件失败')
