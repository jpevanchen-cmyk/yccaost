# 通用支付地基（批次 D）
# 目标：支付「到账」与通道配置不绑死饮食店；堂食/外卖履约由 dining_bridge 接入。
# 本层不做：退款、多订单合并支付包、分账（仍靠后）。

from __future__ import annotations

from django.utils import timezone

from ..models import ShopPaymentSettings
from .base import PayMethodOption


# 将来接入、仅灰色占位的通道（与行业无关）
COMING_SOON_METHODS = [
    PayMethodOption(
        code='alipay',
        label='支付宝',
        description='网页 / 扫码支付',
        coming_soon=True,
    ),
    PayMethodOption(
        code='unionpay',
        label='云闪付',
        description='银联云闪付',
        coming_soon=True,
    ),
    PayMethodOption(
        code='card',
        label='信用卡 / 借记卡',
        description='银行卡在线支付',
        coming_soon=True,
    ),
]


def get_payment_settings(seller_id: str) -> ShopPaymentSettings:
    """获取店铺支付配置，没有则创建默认（通用）"""
    settings, _ = ShopPaymentSettings.objects.get_or_create(seller_id=seller_id)
    return settings


def mark_payment_received(order, payment_method: str, paid_at=None) -> bool:
    """
    通用到账：只改支付相关字段。
    返回 True 表示本次新标记为已付；False 表示本来已是已付（幂等）。
    不负责「备货 / 出餐 / 派单」等行业履约——由接入方在回调里自行处理。
    """
    if getattr(order, 'payment_status', None) == 'paid':
        return False
    order.payment_status = 'paid'
    order.payment_method = payment_method
    order.payment_time = paid_at or timezone.now()
    order.save(update_fields=[
        'payment_status', 'payment_method', 'payment_time', 'updated_at',
    ])
    return True


def build_online_pay_options(settings, *, block_real_wechat: bool = False) -> list[PayMethodOption]:
    """
    通用在线通道列表：微信 / 演示 / 即将开通。
    不含现金与行业文案；现金由行业接入层按场景追加。
    """
    options: list[PayMethodOption] = []

    if settings.enable_wechat and not block_real_wechat:
        ready = settings.wechat_config_ready()
        hint = ''
        if not ready:
            hint = '店主尚未完成微信商户配置，暂不可用'
        elif not (settings.public_site_url or '').strip():
            hint = '未填公网网址时无法收微信自动通知，支付页将轮询查单'
        options.append(
            PayMethodOption(
                code='wechat',
                label='微信支付',
                description='微信扫码，真实扣款',
                enabled=ready,
                hint=hint,
            )
        )
    elif settings.enable_wechat and block_real_wechat:
        options.append(
            PayMethodOption(
                code='wechat',
                label='微信支付',
                description='体验店不可用真付',
                enabled=False,
                hint='体验店铺禁止真实支付；请用演示支付，或到官方小店',
            )
        )

    if settings.enable_simulate:
        options.append(
            PayMethodOption(
                code='wechat_simulate',
                label='演示支付（模拟）',
                description='不扣真钱，用于体验下单流程',
                enabled=True,
                hint='正式上线前请在店铺设置中关闭',
            )
        )

    options.extend(COMING_SOON_METHODS)
    return options
