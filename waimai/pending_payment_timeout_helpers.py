# 待支付超时自动取消（批次 I · 进度 56）
# 截止时间记在订单上；取消前问微信；已取消不救活，晚到账自动退。

from __future__ import annotations

import logging
import os
import threading
from datetime import timedelta

from django.db import close_old_connections, transaction
from django.db.utils import OperationalError, ProgrammingError

from .time_helpers import as_storage_datetime, now_local_wall

logger = logging.getLogger('waimai')

DEFAULT_TIMEOUT_MINUTES = 30
MIN_TIMEOUT_MINUTES = 5
MAX_TIMEOUT_MINUTES = 1440  # 24 小时
SCAN_INTERVAL_SECONDS = 60
FOLLOWUP_HOURS = 24
FOLLOWUP_INTERVAL = timedelta(minutes=30)
WECHAT_QR_WINDOW = timedelta(minutes=10)
WECHAT_QR_MAX = 5
WECHAT_QR_RATE_MESSAGE = '由于请求过于频繁，当前订单无法再申请微信支付。'
ABANDON_WECHAT_CONFIRM = (
    '放弃后这张微信收款码将不能再付。若已经扫过请先等结果。确定放弃当前微信支付吗？'
)

_SCANNER_STARTED = False
_SCANNER_LOCK = threading.Lock()


def clamp_timeout_minutes(raw) -> int:
    """把店主填的分钟夹到 5～1440；空或非法用默认 30。"""
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_MINUTES
    if n < MIN_TIMEOUT_MINUTES:
        return MIN_TIMEOUT_MINUTES
    if n > MAX_TIMEOUT_MINUTES:
        return MAX_TIMEOUT_MINUTES
    return n


def shop_timeout_minutes(seller_id: str) -> int:
    from .payments.core import get_payment_settings

    settings = get_payment_settings(seller_id)
    return clamp_timeout_minutes(getattr(settings, 'pending_pay_timeout_minutes', None))


def pending_pay_stamp_fields(seller_id: str) -> dict:
    """下单时写入本单时限与截止时间（一份真源）。"""
    minutes = shop_timeout_minutes(seller_id)
    now = now_local_wall()
    return {
        'pending_pay_limit_minutes': minutes,
        'pending_pay_deadline': now + timedelta(minutes=minutes),
    }


def timeout_public_message(order) -> str:
    """给客人看的超时取消原因（分钟用本单记下的）。"""
    n = order.pending_pay_limit_minutes or DEFAULT_TIMEOUT_MINUTES
    return f'本订单超过{n}分钟未支付，已自动取消，请重新下单。'


def is_cash_like_pending(order) -> bool:
    """现金 / 货到付款 / 堂食打包现金：不因超时取消。"""
    return (order.payment_method or '') == 'cash'


def is_timeout_candidate(order) -> bool:
    """仍待支付、且不是现金类。未选支付方式的先付单也算。"""
    if order.payment_status != 'pending_payment':
        return False
    if order.order_status in ('cancelled', 'completed'):
        return False
    if is_cash_like_pending(order):
        return False
    return True


def ensure_deadline(order) -> None:
    """旧单没有截止时间：按下单时间 + 本单/店默认分钟补上（不另存第二份事实）。"""
    if order.pending_pay_deadline:
        return
    minutes = order.pending_pay_limit_minutes or shop_timeout_minutes(order.seller_id)
    minutes = clamp_timeout_minutes(minutes)
    created = as_storage_datetime(order.created_at) if order.created_at else now_local_wall()
    order.pending_pay_deadline = created + timedelta(minutes=minutes)
    if not order.pending_pay_limit_minutes:
        order.pending_pay_limit_minutes = minutes
    order.save(update_fields=['pending_pay_deadline', 'pending_pay_limit_minutes', 'updated_at'])


def remaining_seconds(order) -> int | None:
    """还剩几秒；现金类或不适用返回 None；已过点返回 0。"""
    if not is_timeout_candidate(order):
        return None
    ensure_deadline(order)
    deadline = as_storage_datetime(order.pending_pay_deadline)
    now = now_local_wall()
    sec = int((deadline - now).total_seconds())
    return max(0, sec)


def is_overdue(order) -> bool:
    sec = remaining_seconds(order)
    return sec == 0


def _wechat_trade_peek(order) -> str:
    """
    问微信这一单怎样。
    返回 success / unpaid / unknown（unknown 本轮不取消，避免问不到就误杀）。
    """
    from .payments.core import get_payment_settings
    from .payments.wechat_native import query_wechat_order, try_sync_wechat_payment
    from .payments.wechat_refund_helpers import get_wechat_success_record

    if get_wechat_success_record(order):
        return 'success'
    record = (
        order.payment_records.filter(payment_method='wechat')
        .exclude(out_trade_no='')
        .order_by('-created_at')
        .first()
    )
    if not record:
        return 'unpaid'
    settings = get_payment_settings(order.seller_id)
    if not settings.wechat_config_ready():
        return 'unpaid'
    try:
        if try_sync_wechat_payment(record, settings):
            return 'success'
        result = query_wechat_order(record, settings)
    except Exception:
        logger.exception('超时取消前查微信失败 order=%s', order.order_id)
        return 'unknown'
    if result.get('return_code') != 'SUCCESS' or result.get('result_code') != 'SUCCESS':
        return 'unknown'
    state = (result.get('trade_state') or '').upper()
    if state == 'SUCCESS':
        return 'success'
    if state in ('NOTPAY', 'CLOSED', 'REVOKED', 'PAYERROR', 'USERPAYING'):
        return 'unpaid'
    return 'unknown'


def wechat_qr_rate_limited(order) -> bool:
    """本单 10 分钟内新开微信码是否已满 5 张（第 6 次起拦）。"""
    from .models import PaymentRecord

    since = now_local_wall() - WECHAT_QR_WINDOW
    n = PaymentRecord.objects.filter(
        buy_order=order,
        payment_method='wechat',
        created_at__gte=since,
    ).exclude(status='failed').count()
    return n >= WECHAT_QR_MAX


def _pending_wechat_records(order):
    return list(
        order.payment_records.filter(payment_method='wechat', status='pending')
        .exclude(out_trade_no='')
        .order_by('-created_at')
    )


def try_close_wechat_channel(order) -> tuple[str, str]:
    """
    向微信关掉未付收款码。
    返回 (结果, 人话)：paid / closed / unpaid_left / skipped
    关失败不假装已关。
    """
    from .payments.core import get_payment_settings
    from .payments.wechat_native import (
        close_wechat_order,
        mark_wechat_record_closed_locally,
        try_sync_wechat_payment,
    )

    records = _pending_wechat_records(order)
    if not records:
        return 'skipped', ''
    settings = get_payment_settings(order.seller_id)
    if not settings.wechat_config_ready():
        return 'unpaid_left', '未配置微信，无法向支付机构关单'
    unpaid_left = False
    for record in records:
        try:
            if try_sync_wechat_payment(record, settings):
                return 'paid', ''
            result = close_wechat_order(record, settings)
        except Exception:
            logger.exception('向微信关单失败 order=%s', order.order_id)
            unpaid_left = True
            continue
        err = (result.get('err_code') or result.get('err_code_des') or '').upper()
        if 'ORDERPAID' in err or '已支付' in (result.get('err_code_des') or ''):
            if try_sync_wechat_payment(record, settings):
                return 'paid', ''
        if result.get('return_code') == 'SUCCESS' and result.get('result_code') == 'SUCCESS':
            mark_wechat_record_closed_locally(record)
            continue
        unpaid_left = True
        logger.info(
            '微信关单未成功 order=%s msg=%s',
            order.order_id,
            result.get('err_code_des') or result.get('return_msg') or '',
        )
    if unpaid_left:
        return 'unpaid_left', '支付机构暂时无法关闭收款码'
    return 'closed', ''


def abandon_wechat_for_switch(order) -> tuple[bool, str]:
    """客人确认放弃当前微信码：先问、再关、再问。关失败不能假装换走。"""
    order.refresh_from_db()
    if order.order_status == 'cancelled':
        return False, '订单已取消，请重新下单。'
    if order.payment_status == 'paid':
        return False, '该订单已支付'
    peek = _wechat_trade_peek(order)
    order.refresh_from_db()
    if order.payment_status == 'paid' or peek == 'success':
        return False, '该订单已支付'
    if peek == 'unknown':
        return False, '正在向支付机构确认是否已付款，请稍候再试。'
    close_state, close_msg = try_close_wechat_channel(order)
    order.refresh_from_db()
    if close_state == 'paid' or order.payment_status == 'paid':
        return False, '该订单已支付'
    peek2 = _wechat_trade_peek(order)
    order.refresh_from_db()
    if order.payment_status == 'paid' or peek2 == 'success':
        return False, '该订单已支付'
    if close_state == 'unpaid_left' or peek2 == 'unknown':
        return False, close_msg or '暂时无法关闭当前微信支付，请稍候再试。'
    return True, ''


def is_late_pay_followup_candidate(order) -> bool:
    """超时取消后、24 小时内、有非现金真付流水：还要追问机构。"""
    if order.order_status != 'cancelled':
        return False
    if (order.payment_method or '') == 'cash':
        return False
    if not order.cancelled_at:
        return False
    end = as_storage_datetime(order.cancelled_at) + timedelta(hours=FOLLOWUP_HOURS)
    if now_local_wall() >= end:
        return False
    return order.payment_records.filter(payment_method='wechat').exclude(
        out_trade_no='',
    ).exists()


def _mark_followup_queried(order) -> None:
    order.late_pay_last_query_at = now_local_wall()
    order.save(update_fields=['late_pay_last_query_at', 'updated_at'])


def followup_query_cancelled_order(order, *, force: bool = False) -> str:
    """
    已取消单向支付机构追问有没有付。
    返回 skipped / paid_refund / unpaid
    """
    from .payments.core import get_payment_settings
    from .payments.wechat_native import try_sync_wechat_payment
    from .payments.wechat_refund_helpers import get_wechat_success_record

    order.refresh_from_db()
    if not is_late_pay_followup_candidate(order):
        return 'skipped'
    last = as_storage_datetime(order.late_pay_last_query_at) if order.late_pay_last_query_at else None
    if not force and last and now_local_wall() < last + FOLLOWUP_INTERVAL:
        return 'skipped'
    settings = get_payment_settings(order.seller_id)
    _mark_followup_queried(order)
    if get_wechat_success_record(order):
        handle_late_wechat_on_cancelled_order(order)
        return 'paid_refund'
    if not settings.wechat_config_ready():
        return 'unpaid'
    for record in order.payment_records.filter(payment_method='wechat').exclude(out_trade_no=''):
        if record.refund_status == 'success':
            continue
        try:
            if try_sync_wechat_payment(record, settings):
                return 'paid_refund'
        except Exception:
            logger.exception('取消后追问微信失败 order=%s', order.order_id)
    return 'unpaid'


def scan_late_pay_followup_orders() -> int:
    """扫 24 小时窗口内已取消、仍可能晚到账的真付单。"""
    from .models import BuyOrder

    since = now_local_wall() - timedelta(hours=FOLLOWUP_HOURS)
    qs = BuyOrder.objects.filter(
        order_status='cancelled',
        cancelled_at__gte=since,
    ).exclude(payment_method='cash')
    count = 0
    for order in qs.iterator():
        try:
            if followup_query_cancelled_order(order) == 'paid_refund':
                count += 1
        except Exception:
            logger.exception('取消后追问失败 order=%s', getattr(order, 'order_id', ''))
    return count


def handle_extra_wechat_when_order_already_paid(order) -> None:
    """主单已付清（如现金）后又来一笔微信：只退微信，不把主单改成已退款。"""
    from .payments.core import get_payment_settings
    from .payments.wechat_refund_helpers import initiate_wechat_refund_for_order
    from .audit_helpers import write_audit_log

    order.refresh_from_db()
    if order.order_status == 'cancelled':
        handle_late_wechat_on_cancelled_order(order)
        return
    if order.payment_status != 'paid':
        return
    settings = get_payment_settings(order.seller_id)
    ok, msg = initiate_wechat_refund_for_order(
        order, settings, operator='system-extra-wechat',
    )
    write_audit_log(
        action_code='order_status',
        action_label='已付清后多余微信自动退款',
        seller_id=order.seller_id,
        actor=None,
        target_type='order',
        target_id=str(order.order_id),
        summary=f'{order.get_display_order_no()} 已付清后又到一笔微信，自动退：{msg}',
    )
    if not ok:
        logger.warning('多余微信自动退失败 order=%s msg=%s', order.order_id, msg)


@transaction.atomic
def _cancel_unpaid_timeout(order) -> tuple[bool, str]:
    """过点且确认未付：走现有取消字段 + 退名额。已取消则原样返回。"""
    from .models import BuyOrder
    from .order_cancel_helpers import _apply_cancel_fields, _cancel_delivery_if_any

    locked = BuyOrder.objects.select_for_update().get(pk=order.pk)
    if locked.order_status == 'cancelled':
        return True, timeout_public_message(locked)
    if locked.payment_status == 'paid':
        return False, ''
    if not is_timeout_candidate(locked):
        return False, ''

    note = timeout_public_message(locked)
    fields = _apply_cancel_fields(locked, side='system', note=note)
    locked.save(update_fields=fields)
    from .menu_helpers import release_catalog_sales_for_order

    release_catalog_sales_for_order(locked)
    _cancel_delivery_if_any(locked)

    from .audit_helpers import write_audit_log

    write_audit_log(
        action_code='order_status',
        action_label='待支付超时自动取消',
        seller_id=locked.seller_id,
        actor=None,
        target_type='order',
        target_id=str(locked.order_id),
        summary=f'系统超时取消 {locked.get_display_order_no()}：{note}',
    )
    return True, note


def process_overdue_order(order) -> tuple[str, str]:
    """
    处理一张可能过点的单。
    返回 (动作, 给人看的话)：skipped / paid / cancelled / deferred
    """
    from .models import BuyOrder

    order.refresh_from_db()
    if not is_timeout_candidate(order):
        return 'skipped', ''
    if not is_overdue(order):
        return 'skipped', ''

    peek = 'unpaid'
    if (order.payment_method or '') == 'wechat' or order.payment_records.filter(payment_method='wechat').exists():
        peek = _wechat_trade_peek(order)
        order.refresh_from_db()
        if order.payment_status == 'paid':
            return 'paid', ''
        if peek == 'success':
            return 'paid', ''
        if peek == 'unknown':
            return 'deferred', ''
        close_state, _close_msg = try_close_wechat_channel(order)
        order.refresh_from_db()
        if close_state == 'paid' or order.payment_status == 'paid':
            return 'paid', ''
        peek2 = _wechat_trade_peek(order)
        order.refresh_from_db()
        if order.payment_status == 'paid' or peek2 == 'success':
            return 'paid', ''
        if peek2 == 'unknown':
            return 'deferred', ''

    ok, msg = _cancel_unpaid_timeout(order)
    if ok:
        followup_query_cancelled_order(order, force=True)
        return 'cancelled', msg
    fresh = BuyOrder.objects.get(pk=order.pk)
    if fresh.payment_status == 'paid':
        return 'paid', ''
    if fresh.order_status == 'cancelled':
        return 'cancelled', timeout_public_message(fresh)
    return 'skipped', ''


def enforce_pending_pay_or_message(order) -> tuple[bool, str]:
    """
    客人要去支付时：未过点放行；过点则处理（问微信/取消）。
    返回 (还可以付吗, 失败人话)。
    """
    if not is_timeout_candidate(order):
        if order.order_status == 'cancelled':
            return False, timeout_public_message(order) if order.cancel_side == 'system' else '订单已取消，请重新下单。'
        return True, ''
    if not is_overdue(order):
        return True, ''
    action, msg = process_overdue_order(order)
    order.refresh_from_db()
    if action == 'paid' or order.payment_status == 'paid':
        return False, '该订单已支付'
    if action == 'deferred':
        return False, '正在向微信确认是否已付款，请稍候再试。'
    if order.order_status == 'cancelled' or action == 'cancelled':
        return False, msg or timeout_public_message(order)
    return False, timeout_public_message(order)


def handle_late_wechat_on_cancelled_order(order) -> None:
    """已取消之后微信才确认到账：不救活，自动整单退。"""
    from .payments.core import get_payment_settings
    from .payments.wechat_refund_helpers import initiate_wechat_refund_for_order

    order.refresh_from_db()
    if order.order_status != 'cancelled':
        return
    settings = get_payment_settings(order.seller_id)
    ok, msg = initiate_wechat_refund_for_order(
        order, settings, operator='system-timeout',
    )
    order.refresh_from_db()
    from .audit_helpers import write_audit_log

    write_audit_log(
        action_code='order_status',
        action_label='超时取消后到账自动退款',
        seller_id=order.seller_id,
        actor=None,
        target_type='order',
        target_id=str(order.order_id),
        summary=f'{order.get_display_order_no()} 取消后到账，自动退：{msg}',
    )
    if ok:
        record = _refund_record(order)
        if record and record.refund_status == 'processing':
            notify_timeout_refund_update(order, kind='processing')
        elif record and record.refund_status == 'success':
            notify_timeout_refund_update(order, kind='success')
        return
    notify_timeout_refund_update(order, kind='failed', detail=msg)


def _refund_record(order):
    from .payments.wechat_refund_helpers import get_wechat_success_record

    return get_wechat_success_record(order)


def refund_buyer_page_hint(order) -> str:
    """订单页给客人看的退款说明（取消后到账）。"""
    if order.order_status != 'cancelled':
        return ''
    record = _refund_record(order)
    if not record:
        if order.cancel_side == 'system':
            return timeout_public_message(order)
        return ''
    st = record.refund_status or ''
    if st == 'success' or order.payment_status == 'refunded':
        return '本订单已取消。钱已原路退回，请勿再付。'
    if st == 'processing':
        return '本订单已取消。钱会原路退回，请勿再付。'
    if st == 'failed':
        return '钱已到店但自动退未成功，请联系店家；店家已收到提醒。'
    if record.status == 'success':
        return '本订单已取消。钱会原路退回，请勿再付。'
    if order.cancel_side == 'system':
        return timeout_public_message(order)
    return ''


def refund_shop_page_hint(order) -> str:
    """工作台给店主看的醒目说明。"""
    if order.order_status != 'cancelled':
        return ''
    record = _refund_record(order)
    if not record or record.status != 'success':
        if order.cancel_side == 'system':
            return timeout_public_message(order)
        return ''
    st = record.refund_status or ''
    if st == 'failed':
        return (
            f'超时取消后客人钱已到账，但自动退款失败。请尽快在微信商户平台处理。'
            f'订单号 {order.get_display_order_no()}。'
        )
    if st == 'processing':
        return '超时取消后客人钱已到账，退款处理中。请稍后刷新本页查看结果。'
    if st == 'success' or order.payment_status == 'refunded':
        return '超时取消后到账，已自动原路退回。'
    return '超时取消后客人钱已到账，系统正在发起退款。'


def notify_timeout_refund_update(order, *, kind: str, detail: str = '') -> None:
    """退款结果：订单页是底；有邮箱再发信。失败必须店主+客人两边说。"""
    try:
        _notify_shop_refund(order, kind=kind, detail=detail)
    except Exception:
        logger.exception('超时退款通知店主失败 order=%s', order.order_id)
    try:
        _notify_buyer_refund(order, kind=kind)
    except Exception:
        logger.exception('超时退款通知客人失败 order=%s', order.order_id)


def _notify_shop_refund(order, *, kind: str, detail: str = '') -> None:
    from .email_helpers import is_email_ready, send_yecao_mail
    from .email_rate_limit_helpers import KIND_SHOP_TIMEOUT_REFUND
    from .operating_helpers import get_operating_settings
    from .order_notify_helpers import _collect_order_notify_recipients

    if not is_email_ready():
        return
    op = get_operating_settings(order.seller_id)
    recipients = _collect_order_notify_recipients(op)
    if not recipients:
        return
    no = order.get_display_order_no()
    if kind == 'failed':
        subject = f'退款失败须处理 · {no}'
        body = (
            f'订单 {no} 已因超时取消，但客人钱已到账。系统自动退款未成功。\n'
            f'{detail}\n\n'
            '请尽快登录后台处理，并联系客人。'
        )
    elif kind == 'processing':
        subject = f'超时取消后到账，退款处理中 · {no}'
        body = f'订单 {no} 已取消。客人钱已到账，系统已提交原路退款，正在等待微信结果。'
    else:
        subject = f'超时取消后到账，已退款 · {no}'
        body = f'订单 {no} 已取消。客人钱已到账并已原路退回。'
    send_yecao_mail(
        subject=subject,
        message=body,
        recipient_list=recipients,
        kind=KIND_SHOP_TIMEOUT_REFUND,
        dedupe_key=f'order:{order.order_id}:shop_timeout_refund:{kind}',
    )


def _notify_buyer_refund(order, *, kind: str) -> None:
    from .buyer_notify_helpers import _buyer_recipient
    from .email_helpers import send_yecao_mail
    from .email_rate_limit_helpers import KIND_BUYER_TIMEOUT_REFUND

    recipient = _buyer_recipient(order)
    if not recipient:
        return
    no = order.get_display_order_no()
    if kind == 'failed':
        subject = f'退款未成功，请联系店家 · {no}'
        body = (
            f'订单 {no}：钱已到店但自动退未成功，请联系店家；店家已收到提醒。\n'
            f'{timeout_public_message(order)}'
        )
    elif kind == 'processing':
        subject = f'订单已取消，钱将原路退回 · {no}'
        body = f'订单 {no} 已取消。钱会原路退回，请勿再付。'
    else:
        subject = f'钱已退回 · {no}'
        body = f'订单 {no} 已取消。钱已原路退回，请勿再付。'
    send_yecao_mail(
        subject=subject,
        message=body,
        recipient_list=[recipient],
        kind=KIND_BUYER_TIMEOUT_REFUND,
        dedupe_key=f'order:{order.order_id}:buyer_timeout_refund:{kind}',
    )


def scan_overdue_pending_orders() -> int:
    """扫过点待支付单。返回处理张数（含取消与改已付）。"""
    from .models import BuyOrder

    now = now_local_wall()
    qs = BuyOrder.objects.filter(
        payment_status='pending_payment',
    ).exclude(order_status__in=('cancelled', 'completed')).exclude(payment_method='cash')
    # 无截止时间的旧单也看一眼（ensure_deadline 后再判）
    count = 0
    for order in qs.iterator():
        try:
            ensure_deadline(order)
            if order.pending_pay_deadline and as_storage_datetime(order.pending_pay_deadline) > now:
                continue
            action, _msg = process_overdue_order(order)
            if action in ('cancelled', 'paid'):
                count += 1
        except Exception:
            logger.exception('扫待支付超时单失败 order=%s', getattr(order, 'order_id', ''))
    return count


def build_timeout_page_context(order) -> dict:
    """页面倒计时 / 灰按钮 / 人话。"""
    if order.order_status == 'cancelled':
        return {
            'show_countdown': False,
            'remaining_seconds': 0,
            'pay_locked': True,
            'timeout_message': refund_buyer_page_hint(order) or (
                timeout_public_message(order) if order.cancel_side == 'system' else '订单已取消，请重新下单。'
            ),
            'shop_hint': refund_shop_page_hint(order),
        }
    if not is_timeout_candidate(order):
        return {
            'show_countdown': False,
            'remaining_seconds': None,
            'pay_locked': False,
            'timeout_message': '',
            'shop_hint': '',
        }
    sec = remaining_seconds(order)
    locked = sec == 0
    msg = ''
    if locked:
        if order.payment_status == 'pending_payment':
            msg = '支付时限已到，正在确认是否已付款。'
        else:
            msg = timeout_public_message(order)
    return {
        'show_countdown': not locked,
        'remaining_seconds': sec,
        'pay_locked': locked,
        'timeout_message': msg,
        'shop_hint': '',
    }


def _scanner_loop():
    while True:
        close_old_connections()
        try:
            scan_overdue_pending_orders()
            scan_late_pay_followup_orders()
        except (OperationalError, ProgrammingError):
            logger.warning('待支付超时扫描：库表未就绪，稍后重试')
        except Exception:
            logger.exception('待支付超时扫描出错')
        threading.Event().wait(SCAN_INTERVAL_SECONDS)


def maybe_start_pending_pay_scanner() -> None:
    """程序在跑时定期扫；启动立刻扫一次。runserver 父进程不启。"""
    global _SCANNER_STARTED
    if os.environ.get('RUN_MAIN') == 'false':
        return
    with _SCANNER_LOCK:
        if _SCANNER_STARTED:
            return
        _SCANNER_STARTED = True
    try:
        close_old_connections()
        scan_overdue_pending_orders()
        scan_late_pay_followup_orders()
    except (OperationalError, ProgrammingError):
        pass
    except Exception:
        logger.exception('启动时扫待支付超时失败')
    t = threading.Thread(target=_scanner_loop, name='yc-pending-pay-timeout', daemon=True)
    t.start()
