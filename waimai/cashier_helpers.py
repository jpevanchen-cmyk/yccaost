# 实体收银台：当天待支付列表、分页、收款、渠道记忆

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.paginator import Paginator
from django.db import transaction
from django.utils import timezone

from .models import BuyOrder, ShopPaymentSettings
from .order_desk_helpers import format_order_dish_summary
from .order_search_helpers import _apply_keyword_filter
from .payments.core import get_payment_settings
from .shop_work_helpers import _today_range

# 手动登记默认下拉渠道
DEFAULT_CASHIER_CHANNELS = ('现金', '刷卡', '个人码')


def normalize_cashier_page_size(value) -> int:
    """每页条数只允许 10 或 20。"""
    try:
        size = int(value)
    except (TypeError, ValueError):
        return 10
    return 20 if size == 20 else 10


def merge_channel_options(settings: ShopPaymentSettings) -> list[str]:
    """默认渠道 + 本店曾用过的渠道，去重保序。"""
    seen: set[str] = set()
    options: list[str] = []
    for name in list(DEFAULT_CASHIER_CHANNELS) + list(settings.cashier_channel_memory or []):
        text = (str(name) or '').strip()
        if not text or text in seen:
            continue
        seen.add(text)
        options.append(text)
    return options


def remember_cashier_channel(settings: ShopPaymentSettings, channel: str) -> None:
    """把新渠道写入本店记忆。"""
    text = (channel or '').strip()
    if not text:
        return
    memory = [str(x).strip() for x in (settings.cashier_channel_memory or []) if str(x).strip()]
    if text in memory:
        return
    memory.append(text)
    settings.cashier_channel_memory = memory[-30:]
    settings.save(update_fields=['cashier_channel_memory'])


def query_cashier_pending_orders(seller_id: str, *, search_q: str = ''):
    """当天、待支付的订单；可选订单号关键词。"""
    start, end = _today_range()
    qs = BuyOrder.objects.filter(
        seller_id=seller_id,
        payment_status='pending_payment',
        created_at__gte=start,
        created_at__lt=end,
    ).order_by('-created_at')
    keyword = (search_q or '').strip()
    if keyword:
        qs = _apply_keyword_filter(qs, keyword)
    return qs


def parse_cashier_page(request) -> int:
    """从网址读取页码。"""
    try:
        page = int((request.GET.get('page') or '1').strip())
    except ValueError:
        return 1
    return max(1, page)


def build_cashier_pagination(qs, *, page: int, page_size: int) -> dict:
    """分页信息供模板使用。"""
    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)
    return {
        'cashier_page_obj': page_obj,
        'cashier_total_count': paginator.count,
        'cashier_page_size': page_size,
        'cashier_has_other_pages': page_obj.has_other_pages(),
    }


def build_cashier_context(seller_id: str, *, work_user, request) -> dict:
    """组装收银台 Tab 页面数据。"""
    from .staff_account_helpers import (
        PERM_FULFILLMENT_CASH_MANAGE,
        PERM_ORDERS_CASHIER,
        staff_has_permission,
    )

    settings = get_payment_settings(seller_id)
    page_size = normalize_cashier_page_size(settings.cashier_page_size)
    search_q = (request.GET.get('q') or '').strip()
    qs = query_cashier_pending_orders(seller_id, search_q=search_q)
    page = parse_cashier_page(request)
    pagination = build_cashier_pagination(qs, page=page, page_size=page_size)

    rows = []
    for order in pagination['cashier_page_obj']:
        rows.append({
            'order': order,
            'dish_summary': format_order_dish_summary(order.dish_items),
            'fulfillment_label': order.get_fulfillment_display_short(),
        })

    ctx = dict(pagination)
    ctx.update({
        'cashier_rows': rows,
        'cashier_search_q': search_q,
        'cashier_channel_options': merge_channel_options(settings),
        'cashier_can_collect': staff_has_permission(work_user, PERM_ORDERS_CASHIER),
        'cashier_can_manage_shortfall': staff_has_permission(work_user, PERM_FULFILLMENT_CASH_MANAGE),
        'cashier_enable_cash': bool(settings.enable_cash),
        'cashier_empty': not rows and not search_q,
        'cashier_search_empty': not rows and bool(search_q),
    })
    ctx.update(cashier_wechat_options(seller_id, settings))
    ctx.update(cashier_simulate_options(seller_id, settings))
    return ctx


def cashier_simulate_options(seller_id: str, settings: ShopPaymentSettings | None = None) -> dict:
    """收银台演示支付（与支付设置「模拟支付」开关一致）。"""
    settings = settings or get_payment_settings(seller_id)
    enabled = bool(settings.enable_simulate)
    hint = ''
    if not enabled:
        hint = '演示支付未开启；请在支付设置中开启「模拟支付（演示用）」。'
    return {
        'cashier_enable_simulate': enabled,
        'cashier_simulate_hint': hint,
    }


def cashier_wechat_options(seller_id: str, settings: ShopPaymentSettings | None = None) -> dict:
    """收银台是否展示微信扫码（须支付设置已开且参数配齐）。"""
    from .experience_helpers import seller_blocked_from_real_wechat

    settings = settings or get_payment_settings(seller_id)
    blocked = seller_blocked_from_real_wechat(seller_id)
    ready = settings.wechat_config_ready()
    hint = ''
    if blocked:
        hint = '体验店不可用真实微信；请用现金或手动登记，或到官方小店真付。'
    elif settings.enable_wechat and not ready:
        hint = '店主已开微信但商户参数未配齐，暂不能在收银台发起微信收款。'
    elif not settings.enable_wechat:
        hint = ''
    return {
        'cashier_enable_wechat': bool(settings.enable_wechat and ready and not blocked),
        'cashier_wechat_hint': hint,
    }


def cashier_can_start_wechat(order: BuyOrder, seller_id: str) -> tuple[bool, str]:
    """收银台能否对该单发起微信 Native 扫码。"""
    if (order.seller_id or '').strip() != (seller_id or '').strip():
        return False, '订单不属于本店'
    if not _order_in_cashier_scope(order):
        return False, '该订单不是今天待支付单，或已收款'
    opts = cashier_wechat_options(seller_id)
    if not opts['cashier_enable_wechat']:
        return False, opts['cashier_wechat_hint'] or '当前店铺未开通收银台微信收款'
    return True, ''


def cashier_wechat_page_context(order: BuyOrder, seller_id: str, *, client_ip: str) -> tuple[dict | None, str]:
    """
    收银台微信扫码页数据；若无有效 pending 流水则自动下单。
    返回 (context, error_message)。
    """
    ok, msg = cashier_can_start_wechat(order, seller_id)
    if not ok and order.payment_status != 'pending_payment':
        return None, '该订单已收款，无需再扫微信'
    if order.payment_status == 'paid':
        return None, '该订单已收款'

    settings = get_payment_settings(seller_id)
    pending = (
        order.payment_records.filter(payment_method='wechat', status='pending')
        .exclude(code_url='')
        .order_by('-created_at')
        .first()
    )
    if not pending:
        if not ok:
            return None, msg
        from .payments.wechat_native import create_native_payment

        result = create_native_payment(order, settings, client_ip)
        if not result.ok:
            return None, result.message or '微信下单失败'
        pending = (
            order.payment_records.filter(payment_method='wechat', status='pending')
            .exclude(code_url='')
            .order_by('-created_at')
            .first()
        )
    if not pending or not pending.code_url:
        return None, '未能获取微信扫码链接，请稍后重试'

    notify_url = (settings.public_site_url or '').strip()
    return {
        'order': order,
        'code_url': pending.code_url,
        'out_trade_no': pending.out_trade_no,
        'use_notify': bool(notify_url),
        'payment_settings': settings,
    }, ''


def _parse_amount(raw) -> tuple[Decimal | None, str]:
    """解析实收金额。"""
    try:
        amt = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None, '请输入有效的收款金额'
    if amt <= 0:
        return None, '收款金额须大于 0'
    return amt, ''


def _order_in_cashier_scope(order: BuyOrder) -> bool:
    """订单是否仍在收银台可操作范围内。"""
    if order.payment_status != 'pending_payment':
        return False
    start, end = _today_range()
    created = order.created_at
    if timezone.is_naive(created):
        created = timezone.make_aware(created, timezone.get_current_timezone())
    return start <= created < end


def _cashier_only_mark_paid(order: BuyOrder) -> bool:
    """
    店内单若已在备货流中：收银台只补「到账」，不再推 order_status。
    与 confirm_cash_payment 店内分支一致。
    """
    return bool(
        order.is_in_store()
        and order.order_status in ('awaiting_prep', 'preparing', 'ready_pickup', 'completed')
    )


@transaction.atomic
def cashier_confirm_payment(
    order: BuyOrder,
    *,
    actor,
    pay_mode: str,
    collected_amount,
    channel: str = '',
    shortfall_reason: str = '',
    can_manage_shortfall: bool,
) -> tuple[bool, str]:
    """
    收银台确认收款：走统一付完款编排；店内已在备货流中的单只补到账。
    pay_mode: cash | external
    """
    order = BuyOrder.objects.select_for_update().get(pk=order.pk)
    if not _order_in_cashier_scope(order):
        return False, '该订单不是今天待支付单，或已收款'

    settings = get_payment_settings(order.seller_id)
    mode = (pay_mode or '').strip()
    if mode not in ('cash', 'external'):
        return False, '请选择收款方式'

    if mode == 'cash' and not settings.enable_cash:
        return False, '店铺未开启现金支付，请改用手动登记或联系店主'

    amt, err = _parse_amount(collected_amount)
    if err:
        return False, err
    if amt > order.total_amount:
        return False, '实收金额不能高于应付金额，请先找零后按实际应收登记'

    channel_text = (channel or '').strip()
    if mode == 'external':
        if not channel_text:
            return False, '手动登记须填写或选择收款渠道'
        remember_cashier_channel(settings, channel_text)

    shortfall = amt < order.total_amount
    reason = (shortfall_reason or '').strip()
    if shortfall:
        if not can_manage_shortfall:
            return False, '实收少于应付时须由有管理权限的人员确认，请联系店长或店主'
        if len(reason) < 2:
            return False, '少收时必须填写原因（至少两个字）'

    payment_method = 'cash' if mode == 'cash' else 'external'
    only_mark_paid = _cashier_only_mark_paid(order)

    if only_mark_paid:
        from .payments.core import mark_payment_received

        newly = mark_payment_received(order, payment_method)
        if not newly:
            return False, '该订单已收款，无需重复确认'
    else:
        from .payments.service import confirm_order_paid

        confirm_order_paid(order, payment_method)
        order.refresh_from_db()
        if order.payment_status != 'paid':
            return False, '该订单已收款，无需重复确认'

    now = timezone.now()
    order.cash_collected_amount = amt
    order.cash_collected_by = getattr(actor, 'username', '') or ''
    order.cash_collected_at = now
    update_fields = [
        'cash_collected_amount', 'cash_collected_by', 'cash_collected_at', 'updated_at',
    ]
    if shortfall:
        order.cash_shortfall_reason = reason
        order.cash_shortfall_status = 'manager_approved'
        update_fields.extend(['cash_shortfall_reason', 'cash_shortfall_status'])

    order.save(update_fields=update_fields)

    from .audit_helpers import audit_order_status

    parts = [f'收银台收款 {order.get_display_order_no()} · 实收 ¥{amt}']
    if mode == 'external':
        parts.append(f'渠道：{channel_text}')
    if shortfall:
        diff = order.total_amount - amt
        parts.append(f'少收 ¥{diff} · 原因：{reason}')
    audit_order_status(
        order=order,
        actor=actor,
        summary=' · '.join(parts),
    )
    if shortfall:
        return True, f'已按实收 ¥{amt} 确认收款（少收 ¥{order.total_amount - amt}）'
    if only_mark_paid:
        return True, f'已确认收款 ¥{amt}'
    return True, f'已确认收款 ¥{amt}，订单进入备货'


@transaction.atomic
def cashier_confirm_simulate_payment(order: BuyOrder, *, actor) -> tuple[bool, str]:
    """收银台演示支付：不扣真钱，走统一付完款编排。"""
    order = BuyOrder.objects.select_for_update().get(pk=order.pk)
    if not _order_in_cashier_scope(order):
        return False, '该订单不是今天待支付单，或已收款'

    settings = get_payment_settings(order.seller_id)
    if not settings.enable_simulate:
        return False, '演示支付未开启，请在支付设置中开启模拟支付'

    only_mark_paid = _cashier_only_mark_paid(order)
    if only_mark_paid:
        from .payments.core import mark_payment_received

        newly = mark_payment_received(order, 'wechat_simulate')
        if not newly:
            return False, '该订单已收款，无需重复确认'
    else:
        from .payments.service import confirm_order_paid

        confirm_order_paid(order, 'wechat_simulate')
        order.refresh_from_db()
        if order.payment_status != 'paid':
            return False, '该订单已收款，无需重复确认'

    now = timezone.now()
    order.cash_collected_amount = order.total_amount
    order.cash_collected_by = getattr(actor, 'username', '') or ''
    order.cash_collected_at = now
    order.save(update_fields=[
        'cash_collected_amount', 'cash_collected_by', 'cash_collected_at', 'updated_at',
    ])

    from .audit_helpers import audit_order_status

    audit_order_status(
        order=order,
        actor=actor,
        summary=f'收银台演示支付 {order.get_display_order_no()} · ¥{order.total_amount}',
    )
    return True, '演示支付成功，订单进入备货（不扣真钱）'
