# 注册所有支付方式，并生成买家可见的选项列表

from .base import PayMethodOption


# 将来接入的支付方式（仅展示灰色「即将开通」）
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


def build_buyer_pay_options(settings, order=None) -> list[PayMethodOption]:
    """根据店铺配置与订单取餐方式，生成买家可选 + 灰色占位的支付列表"""
    from ..experience_helpers import seller_blocked_from_real_wechat

    options: list[PayMethodOption] = []
    block_real_wechat = seller_blocked_from_real_wechat(getattr(settings, 'seller_id', ''))

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

    if settings.enable_cash:
        if order.is_dine_in():
            cash_label = '现金 · 到店支付（堂食）'
            cash_desc = '在店内用餐，店家接单备餐后用餐时付现金'
        elif order.is_takeaway():
            cash_label = '现金 · 到店支付（打包）'
            cash_desc = '打包自取，店家接单备货后取餐时付现金'
        elif order:
            cash_label = '现金 · 货到付款'
            cash_desc = '配送上门，送达时付现金，店家确认收款后派单'
        else:
            cash_label = '现金'
            cash_desc = '到店自取或货到付款，店家确认收款后开始备货'
        options.append(
            PayMethodOption(
                code='cash',
                label=cash_label,
                description=cash_desc,
                enabled=True,
            )
        )

    options.extend(COMING_SOON_METHODS)
    return options
