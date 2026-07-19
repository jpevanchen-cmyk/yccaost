# 饮食插件：支付接入层（原 payments/dining_bridge）
# 把堂食/打包/外卖特有规则挂在通用支付地基之上。
# 注意：勿在模块顶层 from waimai.payments...（会经 payments/__init__ 再进 service，形成环）

from __future__ import annotations


def apply_dining_after_paid(order) -> list[str]:
    """
    饮食单在线/确认到账后的履约侧效果：进入待备货、写预计时间、同步服务员状态。
    返回建议写入的字段名（便于调用方扩展）；本函数已自行 save。
    """
    update_fields = ['order_status', 'updated_at']
    order.order_status = 'awaiting_prep'

    from .wait_time_helpers import assign_default_wait_time

    assign_default_wait_time(order, at=order.payment_time, save=False)
    update_fields.append('estimated_ready_at')

    from waimai.waiter_helpers import sync_waiter_service_status

    update_fields.extend(sync_waiter_service_status(order))
    order.save(update_fields=list(dict.fromkeys(update_fields)))
    return update_fields


def confirm_dining_order_paid(order, payment_method: str, paid_at=None) -> None:
    """饮食单到账统一入口：先通用到账，再跑饮食履约。"""
    from waimai.payments.core import mark_payment_received

    newly = mark_payment_received(order, payment_method, paid_at=paid_at)
    if not newly:
        return
    # mark_payment_received 已 save；履约再读一次最新支付时间
    apply_dining_after_paid(order)


def dining_guest_onsite_cash_only(order) -> bool:
    """游客堂食：第一阶段只允许现场付现金。"""
    return bool(
        order is not None
        and order.is_guest_order()
        and order.is_dine_in()
    )


def build_dining_cash_option(settings, order):
    """按堂食/打包/外卖拼现金选项；不允许则返回 None。"""
    from waimai.payments.base import PayMethodOption

    guest_onsite_only = dining_guest_onsite_cash_only(order)
    delivery_cod_off = bool(
        order is not None
        and getattr(order, 'fulfillment_type', '') == 'delivery'
        and not getattr(settings, 'enable_cod', True)
    )
    if not (settings.enable_cash or guest_onsite_only) or delivery_cod_off:
        return None

    if order and order.is_dine_in():
        cash_label = '现金 · 到店支付（堂食）'
        cash_desc = '在店内用餐，店家备餐后用餐时付现金'
    elif order and order.is_takeaway():
        cash_label = '现金 · 到店支付（打包）'
        cash_desc = '打包自取，店家备货后取餐时付现金'
    elif order:
        cash_label = '现金 · 货到付款'
        cash_desc = '店家先备货并派骑手，送达时付现金（也可当面扫码付）'
    else:
        cash_label = '现金'
        cash_desc = '到店付或外卖货到付款'

    return PayMethodOption(
        code='cash',
        label=cash_label,
        description=cash_desc,
        enabled=True,
    )


def build_dining_buyer_pay_options(settings, order=None) -> list:
    """饮食店买家支付页选项 = 通用在线通道 + 场景现金。"""
    from waimai.experience_helpers import seller_blocked_from_real_wechat
    from waimai.payments.core import build_online_pay_options

    guest_onsite_only = dining_guest_onsite_cash_only(order)
    block_real = seller_blocked_from_real_wechat(getattr(settings, 'seller_id', ''))

    if guest_onsite_only:
        # 游客堂食：只要现金
        cash = build_dining_cash_option(settings, order)
        return [cash] if cash else []

    options = build_online_pay_options(settings, block_real_wechat=block_real)
    cash = build_dining_cash_option(settings, order)
    if cash:
        # 现金插在「即将开通」之前
        soon = [o for o in options if o.coming_soon]
        main = [o for o in options if not o.coming_soon]
        options = main + [cash] + soon
    return options
