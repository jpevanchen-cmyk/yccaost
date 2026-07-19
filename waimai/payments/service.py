# 支付总线：对外入口（保持原函数名，供页面 / 微信回调调用）
# 通用到账在 core；饮食履约在饮食插件 dining_bridge；本文件负责编排。

from django.db import transaction
from django.utils import timezone

from ..models import BuyOrder, ShopPaymentSettings
from .base import PaymentInitResult
from .core import get_payment_settings, mark_payment_received
from waimai.plugins.dining.dining_bridge import (
    confirm_dining_order_paid,
    dining_guest_onsite_cash_only,
)
from .registry import build_buyer_pay_options
from .wechat_native import create_native_payment, try_sync_wechat_payment

def confirm_order_paid(order: BuyOrder, payment_method: str, paid_at=None):
    """订单标记为已支付；主体订单不调用饮食履约。"""
    if order.fulfillment_type == 'order':
        newly = mark_payment_received(order, payment_method, paid_at=paid_at)
        if newly:
            order.order_status = 'awaiting_prep'
            order.save(update_fields=['order_status', 'updated_at'])
        return
    confirm_dining_order_paid(order, payment_method, paid_at=paid_at)


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

    # 游客堂食单禁止在线/演示支付（第一阶段只做现场付）
    if dining_guest_onsite_cash_only(order) and method != 'cash':
        return PaymentInitResult(ok=False, message='游客堂食请使用现场付现金')

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
        if order.fulfillment_type == 'order':
            # 主体下单不套用饮食预计出餐；先进入待备货，店家后续确认现金。
            order.order_status = 'awaiting_prep'
            update_fields.append('order_status')
            order.save(update_fields=update_fields)
            return PaymentInitResult(
                ok=True,
                redirect_url=f'/order/{order.order_id}/?cash_pending=1&order=1',
            )
        # 到店付（堂食/打包）与外卖货到付款：均立即进入待备货，先备货再收款。
        # 外卖货到付款改正：先备货、派单，送达时由骑手收款（不再「确认收款后才备货派单」）。
        order.order_status = 'awaiting_prep'
        from ..wait_time_helpers import assign_default_wait_time

        assign_default_wait_time(order, save=False)
        update_fields.extend(['order_status', 'estimated_ready_at'])
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


def confirm_cash_payment(order: BuyOrder) -> tuple[bool, str]:
    """卖家确认现金已收"""
    if order.payment_method != 'cash' or order.payment_status != 'pending_payment':
        return False, '该订单不是待确认的现金单'

    if order.is_in_store():
        if order.order_status not in ('awaiting_prep', 'preparing', 'ready_pickup', 'completed'):
            return False, '当前订单状态不能确认收款'
        # 仅到账，不再改履约状态（店内单已在备货流中）
        mark_payment_received(order, 'cash')
        return True, '已确认收款'

    confirm_order_paid(order, 'cash')
    return True, '已确认收款，订单进入备货'


@transaction.atomic
def rider_collect_cash(
    order: BuyOrder, rider_id: str, amount, shortfall_reason: str = '',
) -> tuple[bool, str]:
    """
    外卖货到付款：骑手送达时收现金。
    足额时直接记为已收款；少收时先等买家当面确认，未确认不能交餐结单。
    """
    from decimal import Decimal, InvalidOperation

    order = BuyOrder.objects.select_for_update().get(pk=order.pk)
    if not order.is_delivery_cod():
        return False, '该订单不是外卖现金货到付款单'
    if order.payment_status == 'paid':
        return False, '该订单已收款，无需重复收款'
    if order.payment_status != 'pending_payment':
        return False, '当前订单状态不能收款'

    try:
        amt = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return False, '请输入有效的收款金额'
    if amt <= 0:
        return False, '收款金额须大于 0'
    if amt > order.total_amount:
        return False, '实收金额不能高于应收金额，请先找零后按实际应收登记'

    now = timezone.now()
    order.cash_collected_amount = amt
    order.cash_collected_by = rider_id or ''
    if amt < order.total_amount:
        reason = (shortfall_reason or '').strip()
        if len(reason) < 2:
            return False, '少收时必须填写原因（至少两个字），再请买家当面确认'
        order.cash_shortfall_reason = reason
        order.cash_shortfall_status = 'buyer_pending'
        order.cash_shortfall_buyer_responded_at = None
        order.cash_collected_at = None
        order.payment_status = 'pending_payment'
        order.payment_time = None
        order.save(update_fields=[
            'cash_collected_amount', 'cash_collected_by',
            'cash_shortfall_reason', 'cash_shortfall_status',
            'cash_shortfall_buyer_responded_at', 'cash_collected_at',
            'payment_status', 'payment_time', 'updated_at',
        ])
        diff = order.total_amount - amt
        return True, (
            f'已向买家发起少收确认：实付 ¥{amt}，少付 ¥{diff}。'
            '买家确认前不能交餐或结单'
        )

    had_shortfall = bool(order.cash_shortfall_status)
    order.cash_collected_at = now
    order.payment_status = 'paid'
    order.payment_time = now
    order.cash_shortfall_status = 'resolved_full' if had_shortfall else ''
    if not had_shortfall:
        order.cash_shortfall_reason = ''
        order.cash_shortfall_buyer_responded_at = None
    order.save(update_fields=[
        'cash_collected_amount', 'cash_collected_by', 'cash_collected_at',
        'payment_status', 'payment_time', 'cash_shortfall_status',
        'cash_shortfall_reason', 'cash_shortfall_buyer_responded_at', 'updated_at',
    ])
    return True, f'已确认收款 ¥{amt}'


@transaction.atomic
def buyer_respond_cash_shortfall(order: BuyOrder, buyer_id: str, *, accept: bool) -> tuple[bool, str]:
    """买家当面确认或拒绝配送员登记的少收金额。"""
    order = BuyOrder.objects.select_for_update().get(pk=order.pk)
    if order.buyer_id != (buyer_id or ''):
        return False, '您不能处理这份订单'
    if order.cash_shortfall_status != 'buyer_pending':
        return False, '这份少收申请已经处理，不能重复确认'

    now = timezone.now()
    order.cash_shortfall_buyer_responded_at = now
    if not accept:
        order.cash_shortfall_status = 'buyer_rejected'
        order.save(update_fields=[
            'cash_shortfall_status', 'cash_shortfall_buyer_responded_at', 'updated_at',
        ])
        return True, '已拒绝确认。配送员不能交餐或结单，请当面协商或由配送员电话联系管理人员'

    order.cash_shortfall_status = 'buyer_confirmed'
    order.cash_collected_at = now
    order.payment_status = 'paid'
    order.payment_time = now
    order.save(update_fields=[
        'cash_shortfall_status', 'cash_shortfall_buyer_responded_at',
        'cash_collected_at', 'payment_status', 'payment_time', 'updated_at',
    ])
    return True, f'您已确认实付 ¥{order.cash_collected_amount}，配送员现在可以交餐'


@transaction.atomic
def mark_cash_exception(order: BuyOrder, rider_id: str, note: str) -> tuple[bool, str]:
    """配送员电话沟通后，在订单上留下异常与管理指示。"""
    order = BuyOrder.objects.select_for_update().get(pk=order.pk)
    note = (note or '').strip()
    if len(note) < 5:
        return False, '请写明电话沟通和得到的指示（至少五个字）'
    if order.cash_shortfall_status not in ('buyer_pending', 'buyer_rejected', 'exception'):
        return False, '当前订单没有需要标记的少收异常'
    if order.cash_collected_by != (rider_id or ''):
        return False, '只能由本单收款配送员标记异常'
    order.cash_shortfall_status = 'exception'
    order.cash_exception_note = note
    order.cash_exception_marked_by = rider_id or ''
    order.cash_exception_marked_at = timezone.now()
    order.save(update_fields=[
        'cash_shortfall_status', 'cash_exception_note',
        'cash_exception_marked_by', 'cash_exception_marked_at', 'updated_at',
    ])
    return True, '已标记现金异常并保存电话沟通备注，请等待管理人员处理'


@transaction.atomic
def manager_approve_cash_exception(order: BuyOrder, manager_id: str, note: str) -> tuple[bool, str]:
    """管理人员同意按少收金额交餐，并直接兜底完成配送。"""
    order = BuyOrder.objects.select_for_update().select_related('delivery_order').get(pk=order.pk)
    note = (note or '').strip()
    if len(note) < 5:
        return False, '请写明兜底决定和原因（至少五个字）'
    if order.cash_shortfall_status not in ('buyer_pending', 'buyer_rejected', 'exception'):
        return False, '当前订单没有可兜底的现金异常'
    delivery = getattr(order, 'delivery_order', None)
    if not delivery or delivery.delivery_status != 'picked_up':
        return False, '配送员尚未取餐，当前不能兜底结单'

    now = timezone.now()
    order.cash_shortfall_status = 'manager_approved'
    order.cash_collected_at = now
    order.payment_status = 'paid'
    order.payment_time = now
    order.cash_exception_note = note
    order.cash_exception_resolved_by = manager_id or ''
    order.cash_exception_resolved_at = now
    order.order_status = 'completed'
    order.save(update_fields=[
        'cash_shortfall_status', 'cash_collected_at', 'payment_status',
        'payment_time', 'cash_exception_note', 'cash_exception_resolved_by',
        'cash_exception_resolved_at', 'order_status', 'updated_at',
    ])
    delivery.delivery_status = 'completed'
    delivery.completed_at = now
    delivery.save(update_fields=['delivery_status', 'completed_at', 'updated_at'])
    return True, '管理人员已按少收金额兜底结单，处理决定已留痕'


def confirm_cash_remittance(orders, confirmer_id: str) -> tuple[int, str]:
    """
    骑手入金：店主/店长确认骑手交回的现金。
    orders 为已收款未入金的订单集合；返回 (确认笔数, 提示)。
    """
    now = timezone.now()
    count = 0
    for order in orders:
        if not order.cash_remit_pending():
            continue
        order.cash_remitted_at = now
        order.cash_remitted_by = confirmer_id or ''
        order.save(update_fields=['cash_remitted_at', 'cash_remitted_by', 'updated_at'])
        count += 1
    if count == 0:
        return 0, '没有需要确认入金的现金单'
    return count, f'已确认 {count} 笔现金入金'


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
    # 未收款结案也算翻台：关掉桌台会话
    from ..guest_order_helpers import maybe_close_table_session_after_settle
    maybe_close_table_session_after_settle(order)
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
