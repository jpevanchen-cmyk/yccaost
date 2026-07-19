# 支付方式注册入口：主体订单走通用支付；饮食订单走插件接入。

from waimai.plugins.dining.dining_bridge import build_dining_buyer_pay_options

from .base import PayMethodOption
from .core import build_online_pay_options


def _build_basic_order_pay_options(settings) -> list[PayMethodOption]:
    """主体「下单」通道：通用在线支付 + 无业态文案的现金。"""
    from ..experience_helpers import seller_blocked_from_real_wechat

    options = build_online_pay_options(
        settings,
        block_real_wechat=seller_blocked_from_real_wechat(
            getattr(settings, 'seller_id', ''),
        ),
    )
    if settings.enable_cash:
        cash = PayMethodOption(
            code='cash',
            label='现金',
            description='按订单约定与店家完成现金付款',
            enabled=True,
        )
        soon = [option for option in options if option.coming_soon]
        main = [option for option in options if not option.coming_soon]
        options = main + [cash] + soon
    return options


def build_buyer_pay_options(settings, order=None):
    """
    根据店铺配置与订单场景生成买家可选支付列表。
    主体「下单」不进入饮食履约；饮食三通道交给饮食插件。
    """
    if order is not None and getattr(order, 'fulfillment_type', '') == 'order':
        return _build_basic_order_pay_options(settings)
    return build_dining_buyer_pay_options(settings, order=order)
