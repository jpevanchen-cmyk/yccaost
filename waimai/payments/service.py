# 支付总线：读取店铺配置、发起支付、标记到账

from datetime import timedelta

from django.utils import timezone

from ..models import BuyOrder, PaymentRecord, ShopPaymentSettings
from ..time_helpers import format_beijing_time
from .base import PaymentInitResult
from .registry import build_buyer_pay_options
from .wechat_native import create_native_payment, try_sync_wechat_payment

# 店家开始备货时可选的出餐/取餐时间（分钟）
IN_STORE_ETA_MINUTES = (10, 15, 20, 30)


def get_payment_settings(seller_id: str) -> ShopPaymentSettings:
    """获取店铺支付配置，没有则创建默认"""
    settings, _ = ShopPaymentSettings.objects.get_or_create(seller_id=seller_id)
    return settings


def confirm_order_paid(order: BuyOrder, payment_method: str, paid_at=None):
    """订单标记为已支付（备货前统一入口）"""
    if order.payment_status == 'paid':
        return
    order.payment_status = 'paid'
    order.order_status = 'awaiting_prep'
    order.payment_method = payment_method
    order.payment_time = paid_at or timezone.now()
    update_fields = [
        'payment_status', 'order_status', 'payment_method', 'payment_time', 'updated_at',
    ]
    # 若服务员已按份把菜全部送达，则付款后不应再回到「待开始备货」。
    from ..waiter_helpers import sync_waiter_service_status

    update_fields.extend(sync_waiter_service_status(order))
    order.save(update_fields=list(dict.fromkeys(update_fields)))


def build_pay_page_context(order: BuyOrder) -> dict:
    """支付页所需上下文"""
    settings = get_payment_settings(order.seller_id)
    options = build_buyer_pay_options(settings, order=order)

    pending_wechat = (
        order.payment_records.filter(payment_method='wechat', status='pending')
        .exclude(code_url='')
        .order_by('-created_at')
        .first()
    )

    return {
        'order': order,
        'pay_options': options,
        'payment_settings': settings,
        'pending_wechat_record': pending_wechat,
        'has_selectable_method': any(o.enabled and not o.coming_soon for o in options),
    }


def initiate_payment(order: BuyOrder, method: str, client_ip: str) -> PaymentInitResult:
    """买家选定支付方式后，路由到对应插头"""
    settings = get_payment_settings(order.seller_id)
    options = {o.code: o for o in build_buyer_pay_options(settings, order=order)}

    if method not in options:
        return PaymentInitResult(ok=False, message='不支持的支付方式')

    option = options[method]
    if option.coming_soon:
        return PaymentInitResult(ok=False, message='该支付方式即将开通')
    if not option.enabled:
        return PaymentInitResult(ok=False, message=option.hint or '该支付方式暂不可用')

    if method == 'wechat_simulate':
        confirm_order_paid(order, 'wechat_simulate')
        return PaymentInitResult(
            ok=True,
            redirect_url=(
                f'/shop/?seller_id={order.seller_id}&success=1'
                f'&fulfillment={order.fulfillment_type}'
            ),
        )

    if method == 'cash':
        order.payment_method = 'cash'
        update_fields = ['payment_method', 'updated_at']
        if order.is_in_store():
            order.order_status = 'awaiting_shop_confirm'
            update_fields.append('order_status')
        order.save(update_fields=update_fields)
        suffix = 'cod=1'
        if order.is_dine_in():
            suffix = 'dine_in=1'
        elif order.is_takeaway():
            suffix = 'takeaway=1'
        return PaymentInitResult(
            ok=True,
            redirect_url=f'/order/{order.order_id}/?cash_pending=1&{suffix}',
        )

    if method == 'wechat':
        from ..experience_helpers import seller_blocked_from_real_wechat

        if seller_blocked_from_real_wechat(order.seller_id):
            return PaymentInitResult(
                ok=False,
                message='体验店铺无法使用真实微信支付，请改用演示支付或到官方小店',
            )
        return create_native_payment(order, settings, client_ip)

    return PaymentInitResult(ok=False, message='支付方式尚未实现')


def confirm_in_store_order(order: BuyOrder, eta_minutes: int) -> tuple[bool, str]:
    """堂食/打包到店单：开始备货并反馈预计出餐/取餐时间（不确认收款）"""
    if not order.is_awaiting_in_store_order_confirm():
        return False, '该订单不是待备货的堂食/打包单'
    if eta_minutes not in IN_STORE_ETA_MINUTES:
        return False, '请选择有效的出餐时间'

    now = timezone.now()
    order.order_status = 'preparing'
    order.preparing_at = now
    order.estimated_ready_at = now + timedelta(minutes=eta_minutes)
    order.save(update_fields=[
        'order_status', 'preparing_at', 'estimated_ready_at', 'updated_at',
    ])

    ready_str = format_beijing_time(order.estimated_ready_at)
    if order.is_dine_in():
        return True, f'已开始备餐，预计 {ready_str} 可出餐'
    return True, f'已开始备货，预计 {ready_str} 可取餐'


def confirm_cash_payment(order: BuyOrder) -> tuple[bool, str]:
    """卖家确认现金已收"""
    if order.payment_method != 'cash' or order.payment_status != 'pending_payment':
        return False, '该订单不是待确认的现金单'

    if order.is_in_store():
        if order.is_awaiting_in_store_order_confirm():
            return False, '请先选择预计时间并开始备货，再确认收款'
        if order.order_status not in ('preparing', 'ready_pickup', 'completed'):
            return False, '当前订单状态不能确认收款'
        order.payment_status = 'paid'
        order.payment_time = timezone.now()
        order.save(update_fields=['payment_status', 'payment_time', 'updated_at'])
        return True, '已确认收款'

    confirm_order_paid(order, 'cash')
    return True, '已确认收款，订单进入备货'


def close_uncollected_cash_order(order: BuyOrder, reason: str) -> tuple[bool, str]:
    """到店付现金但确实未收到款：备注原因后结案并结束订单"""
    reason = (reason or '').strip()
    if len(reason) < 2:
        return False, '请填写无法收款原因（至少两个字）'
    if not order.can_close_as_uncollected():
        return False, '当前订单不能使用「无法收款结单」'

    order.payment_status = 'uncollected'
    order.cash_uncollected_reason = reason
    order.order_status = 'completed'
    order.save(update_fields=[
        'payment_status', 'cash_uncollected_reason', 'order_status', 'updated_at',
    ])
    return True, '已按未收款结案并结束订单'


def poll_wechat_payment(order: BuyOrder) -> bool:
    """轮询微信查单（买家在扫码页等待时）"""
    settings = get_payment_settings(order.seller_id)
    if not settings.wechat_config_ready():
        return False

    record = (
        order.payment_records.filter(payment_method='wechat', status='pending')
        .order_by('-created_at')
        .first()
    )
    if not record:
        return order.payment_status == 'paid'

    return try_sync_wechat_payment(record, settings)


def handle_wechat_notify(xml_body: bytes) -> tuple[bytes, int]:
    """微信异步通知入口：验签并更新订单"""
    from .wechat_native import notify_fail_xml, notify_success_xml, parse_and_handle_notify

    all_settings = ShopPaymentSettings.objects.exclude(wechat_mch_id='')
    settings_map = {s.wechat_mch_id.strip(): s for s in all_settings if s.wechat_mch_id.strip()}

    ok, msg = parse_and_handle_notify(xml_body, settings_map)
    if ok:
        return notify_success_xml(), 200
    return notify_fail_xml(msg), 400
