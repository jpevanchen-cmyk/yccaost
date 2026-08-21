# 84a · 资金总流水：写入、状态追踪、查询展示（§5.8.7）

from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import BuyOrder, FundLedgerEntry, FundLedgerStatusTrack
from .time_helpers import format_local, now_local_wall

LEDGER_SCHEMA_VERSION = '1'

# 业务类型（库固定码 → 界面中文）
BUSINESS_TYPE_LABELS: dict[str, str] = {
    'payment_method_selected': '选择支付方式',
    'payment_received': '确认收款',
    'wechat_scan_initiated': '发起微信扫码',
    'wechat_payment_success': '微信到账',
    'wechat_payment_closed': '微信关闭',
    'wechat_refund_processing': '微信退款处理中',
    'wechat_refund_success': '微信退款完成',
    'shop_order_cancelled': '店家取消订单',
    'demo_payment_success': '演示支付到账',
    'rider_cash_collected': '骑手送达收款',
    'cash_remittance_confirmed': '入金确认',
    'cash_exception_settled': '少收兜底结单',
}

PAYMENT_METHOD_LABELS: dict[str, str] = {
    'cash': '现金',
    'wechat': '微信',
    'wechat_simulate': '演示支付',
    'external': '外部门店',
    'card': '银行卡',
}

FUND_LEDGER_TABS: list[tuple[str, str]] = [
    ('all', '全部'),
    ('cash', '现金'),
    ('wechat', '微信'),
    ('wechat_simulate', '演示'),
    ('external', '外部门店'),
]

# 84b · 查询视图（仍读同一张总流水，不另建账）
FUND_LEDGER_VIEWS: list[tuple[str, str]] = [
    ('detail', '明细'),
    ('daily', '按日汇总'),
    ('remit', '入金历史'),
    ('shortfall', '少收明细'),
    ('alerts', '异常告警'),
]

# 同一订单不应重复出现的「真正到账」类业务（入金确认不算第二笔到账）
DUPLICATE_INCOME_BUSINESS_TYPES = frozenset({
    'payment_received',
    'wechat_payment_success',
    'demo_payment_success',
    'rider_cash_collected',
    'cash_exception_settled',
})

# 同一订单不应重复完成的退款类业务
DUPLICATE_REFUND_BUSINESS_TYPES = frozenset({
    'wechat_refund_success',
})

TRACKABLE_FIELDS = ('entry_status', 'fund_status', 'refund_status')


def _money2(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _generate_display_no() -> str:
    """生成对外展示的流水号。"""
    now = now_local_wall()
    return f'FL-{format_local(now, "%Y%m%d")}-{uuid.uuid4().hex[:8].upper()}'


def _label_for(field: str, code: str) -> str:
    if not code:
        return '—'
    if field == 'business_type':
        return BUSINESS_TYPE_LABELS.get(code, code)
    if field == 'payment_method':
        return PAYMENT_METHOD_LABELS.get(code, code)
    choices_map = {
        'direction': dict(FundLedgerEntry.DIRECTION_CHOICES),
        'entry_status': dict(FundLedgerEntry.ENTRY_STATUS_CHOICES),
        'fund_status': dict(FundLedgerEntry.FUND_STATUS_CHOICES),
        'refund_status': dict(FundLedgerEntry.REFUND_STATUS_CHOICES),
    }
    return choices_map.get(field, {}).get(code, code)


def fund_status_display(code: str, *, business_type: str = '') -> str:
    """资金状态中文；微信扫码等待阶段旧数据兼容显示为「待到账」。"""
    if not code:
        return '—'
    if code == FundLedgerEntry.FUND_STATUS_PENDING_ARRIVAL:
        return '待到账'
    if code == FundLedgerEntry.FUND_STATUS_NOT_APPLICABLE and business_type == 'wechat_scan_initiated':
        return '待到账'
    return _label_for('fund_status', code)


def _track_value_label(field: str, code: str, *, business_type: str = '') -> str:
    if field == 'fund_status':
        return fund_status_display(code, business_type=business_type)
    return _label_for(field, code)


def compact_ledger_display_no(display_no: str) -> str:
    """列表用短流水号：去掉日期，保留 FL-随机段。"""
    text = (display_no or '').strip()
    if not text:
        return '—'
    parts = text.split('-')
    if len(parts) >= 3 and parts[0].upper() == 'FL':
        return f'FL-{parts[-1]}'
    return text


def compact_order_display_no(order: BuyOrder | None) -> str:
    """列表用短订单号：只留短号。"""
    if not order:
        return '—'
    return order.get_order_short_code() or '—'


def entry_display_row(
    entry: FundLedgerEntry,
    *,
    alert_flags: list[str] | None = None,
) -> dict[str, str]:
    """模板用：一行流水的中文展示字段。"""
    order = entry.buy_order if entry.buy_order_id else None
    flags = list(alert_flags or [])
    return {
        'ledger_id': str(entry.ledger_id),
        'order_id': str(order.order_id) if order else '',
        'display_no': compact_ledger_display_no(entry.display_no),
        'display_no_full': entry.display_no,
        'order_no': compact_order_display_no(order),
        'order_no_full': order.get_display_order_no() if order else '—',
        'direction': _label_for('direction', entry.direction),
        'amount': f'¥{entry.amount}',
        'payment_method': _label_for('payment_method', entry.payment_method),
        'business_type': _label_for('business_type', entry.business_type),
        'entry_status': _label_for('entry_status', entry.entry_status),
        'fund_status': fund_status_display(entry.fund_status, business_type=entry.business_type),
        'refund_status': _label_for('refund_status', entry.refund_status),
        'operator': entry.operator or '系统',
        'source': entry.source or '—',
        'reference_key': entry.reference_key or '—',
        'note': entry.note or '',
        'occurred_at': format_local(entry.occurred_at, '%Y-%m-%d %H:%M'),
        'is_alert': bool(flags),
        'alert_label': '、'.join(flags),
    }


def _append_status_track(
    ledger: FundLedgerEntry,
    changed_field: str,
    value_before: str,
    value_after: str,
    *,
    operator: str = '',
    source: str = '',
    note: str = '',
) -> None:
    if value_before == value_after:
        return
    FundLedgerStatusTrack.objects.create(
        ledger=ledger,
        changed_field=changed_field,
        value_before=value_before or '',
        value_after=value_after or '',
        operator=operator or '',
        source=source or '',
        note=note or '',
    )


def _record_initial_tracks(ledger: FundLedgerEntry, *, operator: str, source: str) -> None:
    for field in TRACKABLE_FIELDS:
        value = getattr(ledger, field, '') or ''
        if value:
            _append_status_track(
                ledger, field, '', value, operator=operator, source=source, note='首次记录',
            )


@transaction.atomic
def create_fund_ledger_entry(
    order: BuyOrder,
    *,
    direction: str,
    amount,
    payment_method: str,
    business_type: str,
    source: str = '',
    operator: str = '',
    entry_status: str = FundLedgerEntry.ENTRY_STATUS_SUCCESS,
    fund_status: str = '',
    refund_status: str = '',
    related_ledger: FundLedgerEntry | None = None,
    reference_key: str = '',
    note: str = '',
    occurred_at=None,
) -> FundLedgerEntry:
    """新建一条资金流水并写首条状态追踪。"""
    ledger = FundLedgerEntry.objects.create(
        display_no=_generate_display_no(),
        seller_id=order.seller_id,
        buy_order=order,
        direction=direction,
        amount=_money2(amount),
        payment_method=payment_method,
        fund_status=fund_status or '',
        refund_status=refund_status or '',
        business_type=business_type,
        source=source or '',
        entry_status=entry_status,
        related_ledger=related_ledger,
        occurred_at=occurred_at or now_local_wall(),
        operator=operator or '',
        reference_key=(reference_key or '').strip(),
        schema_version=LEDGER_SCHEMA_VERSION,
        note=(note or '').strip()[:300],
    )
    _record_initial_tracks(ledger, operator=operator, source=source)
    return ledger


def record_fund_ledger_if_absent(
    order: BuyOrder,
    *,
    reference_key: str,
    **kwargs: Any,
) -> FundLedgerEntry | None:
    """同一 reference_key 只写一次（防双记）。"""
    key = (reference_key or '').strip()
    if not key:
        return create_fund_ledger_entry(order, reference_key='', **kwargs)
    existing = FundLedgerEntry.objects.filter(
        seller_id=order.seller_id,
        reference_key=key,
    ).first()
    if existing:
        return None
    try:
        return create_fund_ledger_entry(order, reference_key=key, **kwargs)
    except IntegrityError:
        return FundLedgerEntry.objects.filter(seller_id=order.seller_id, reference_key=key).first()


@transaction.atomic
def transition_fund_ledger_entry(
    ledger: FundLedgerEntry,
    *,
    entry_status: str | None = None,
    fund_status: str | None = None,
    refund_status: str | None = None,
    operator: str = '',
    source: str = '',
    note: str = '',
) -> FundLedgerEntry:
    """更新流水最新态并追加追踪记录。"""
    updates: list[str] = []
    changes = {
        'entry_status': entry_status,
        'fund_status': fund_status,
        'refund_status': refund_status,
    }
    for field, new_val in changes.items():
        if new_val is None:
            continue
        old_val = getattr(ledger, field, '') or ''
        if old_val == new_val:
            continue
        _append_status_track(
            ledger, field, old_val, new_val, operator=operator, source=source, note=note,
        )
        setattr(ledger, field, new_val)
        updates.append(field)
    if updates:
        ledger.save(update_fields=[*updates, 'updated_at'])
    return ledger


def find_ledger_by_reference(seller_id: str, reference_key: str) -> FundLedgerEntry | None:
    key = (reference_key or '').strip()
    if not key:
        return None
    return FundLedgerEntry.objects.filter(seller_id=seller_id, reference_key=key).first()


def list_order_fund_ledger_entries(order: BuyOrder) -> list[dict]:
    """订单详情：本单资金明细 + 追踪链摘要。"""
    rows = []
    for entry in order.fund_ledger_entries.prefetch_related('status_tracks').order_by('occurred_at', 'ledger_id'):
        tracks = [
            {
                'field': track.changed_field,
                'before': _track_value_label(
                    track.changed_field, track.value_before, business_type=entry.business_type,
                ),
                'after': _track_value_label(
                    track.changed_field, track.value_after, business_type=entry.business_type,
                ),
                'at': format_local(track.changed_at, '%m-%d %H:%M'),
                'operator': track.operator or '系统',
            }
            for track in entry.status_tracks.all()
        ]
        rows.append({'entry': entry_display_row(entry), 'tracks': tracks})
    return rows


TRACK_FIELD_LABELS = {
    'entry_status': '流水状态',
    'fund_status': '资金状态',
    'refund_status': '退款状态',
}


def build_ledger_entry_drawer_context(entry: FundLedgerEntry) -> dict:
    """浮层：单笔流水详情 + 状态追踪。"""
    related = entry.related_ledger
    tracks = [
        {
            'field': TRACK_FIELD_LABELS.get(track.changed_field, track.changed_field),
            'before': _track_value_label(
                track.changed_field, track.value_before, business_type=entry.business_type,
            ),
            'after': _track_value_label(
                track.changed_field, track.value_after, business_type=entry.business_type,
            ),
            'at': format_local(track.changed_at, '%Y-%m-%d %H:%M'),
            'operator': track.operator or '系统',
            'note': track.note or '',
        }
        for track in entry.status_tracks.all()
    ]
    row = entry_display_row(entry)
    row['related_ledger_id'] = str(related.ledger_id) if related else ''
    row['related_display_no'] = compact_ledger_display_no(related.display_no) if related else ''
    row['related_display_no_full'] = related.display_no if related else ''
    return {'row': row, 'tracks': tracks}


def build_order_drawer_context(order: BuyOrder) -> dict:
    """浮层：订单摘要 + 本单资金明细。"""
    from .order_shell_helpers import build_order_shell

    return {
        'order': order,
        'order_shell': build_order_shell(order),
        'fund_ledger_rows': list_order_fund_ledger_entries(order),
        'order_no_short': compact_order_display_no(order),
        'order_no_full': order.get_display_order_no(),
    }


def _parse_ledger_day(raw_value: str, *, end_of_day: bool = False):
    """解析 YYYY-MM-DD 为系统本地日界时刻；非法则返回 None。"""
    from datetime import datetime, time

    text = (raw_value or '').strip()
    if not text:
        return None
    try:
        day = datetime.strptime(text, '%Y-%m-%d').date()
    except ValueError:
        return None
    if end_of_day:
        return datetime.combine(day, time(23, 59, 59))
    return datetime.combine(day, time.min)


def detect_fund_ledger_order_alerts(seller_id: str) -> dict[str, list[str]]:
    """
    扫本店总流水，标出疑似双收/双退的订单。
    只读汇总，不另存第二份账。
    """
    from collections import defaultdict

    income_counts: dict[str, int] = defaultdict(int)
    refund_counts: dict[str, int] = defaultdict(int)
    qs = (
        FundLedgerEntry.objects.filter(
            seller_id=seller_id,
            entry_status=FundLedgerEntry.ENTRY_STATUS_SUCCESS,
        )
        .exclude(buy_order_id=None)
        .values_list('buy_order_id', 'business_type')
    )
    for order_id, business_type in qs.iterator():
        key = str(order_id)
        if business_type in DUPLICATE_INCOME_BUSINESS_TYPES:
            income_counts[key] += 1
        if business_type in DUPLICATE_REFUND_BUSINESS_TYPES:
            refund_counts[key] += 1

    alerts: dict[str, list[str]] = {}
    for order_id, count in income_counts.items():
        if count >= 2:
            alerts.setdefault(order_id, []).append('疑似双收')
    for order_id, count in refund_counts.items():
        if count >= 2:
            alerts.setdefault(order_id, []).append('疑似双退')
    return alerts


def build_fund_ledger_daily_summary(
    seller_id: str,
    *,
    year_month: str,
    payment_method: str = 'all',
    max_rows: int = 62,
) -> dict:
    """按发生日汇总总流水（成功态）；同一数据源现算。"""
    from collections import defaultdict

    from .time_helpers import to_local

    bucket: dict[str, dict] = defaultdict(lambda: {
        'entry_count': 0,
        'income_amount': Decimal('0'),
        'expense_amount': Decimal('0'),
        'income_count': 0,
        'expense_count': 0,
        'alert_hint_count': 0,
    })

    qs = FundLedgerEntry.objects.filter(
        seller_id=seller_id,
        entry_status=FundLedgerEntry.ENTRY_STATUS_SUCCESS,
    )
    if payment_method and payment_method != 'all':
        qs = qs.filter(payment_method=payment_method)

    for entry in qs.only('occurred_at', 'direction', 'amount').iterator():
        day = to_local(entry.occurred_at).date().isoformat()
        if year_month and not day.startswith(year_month):
            continue
        row = bucket[day]
        row['entry_count'] += 1
        amount = _money2(entry.amount)
        if entry.direction == FundLedgerEntry.DIRECTION_EXPENSE:
            row['expense_amount'] += amount
            row['expense_count'] += 1
        else:
            row['income_amount'] += amount
            row['income_count'] += 1

    sorted_days = sorted(bucket.keys(), reverse=True)[:max_rows]
    rows = []
    for day in sorted_days:
        data = bucket[day]
        income = _money2(data['income_amount'])
        expense = _money2(data['expense_amount'])
        rows.append({
            'date': day,
            'entry_count': data['entry_count'],
            'income_count': data['income_count'],
            'expense_count': data['expense_count'],
            'income_amount': income,
            'expense_amount': expense,
            'net_amount': _money2(income - expense),
        })

    totals = {
        'entry_count': sum(row['entry_count'] for row in rows),
        'income_count': sum(row['income_count'] for row in rows),
        'expense_count': sum(row['expense_count'] for row in rows),
        'income_amount': _money2(sum((row['income_amount'] for row in rows), Decimal('0'))),
        'expense_amount': _money2(sum((row['expense_amount'] for row in rows), Decimal('0'))),
        'net_amount': _money2(sum((row['net_amount'] for row in rows), Decimal('0'))),
    }
    return {
        'rows': rows,
        'totals': totals,
        'year_month': year_month,
    }


def _apply_fund_ledger_search(qs, q: str):
    """流水号 / 订单号 / 备注 / 依据编号 模糊搜。"""
    from django.db.models import Q

    text = (q or '').strip()
    if not text:
        return qs
    filters = (
        Q(display_no__icontains=text)
        | Q(note__icontains=text)
        | Q(reference_key__icontains=text)
        | Q(operator__icontains=text)
        | Q(buy_order__order_id__icontains=text)
    )
    # 短号：去掉横线后按订单 UUID 前缀试匹配
    compact = text.replace('-', '').strip()
    if len(compact) >= 4:
        filters = filters | Q(buy_order__order_id__istartswith=compact[:8])
    return qs.filter(filters)


def build_seller_fund_ledger_context(seller_id: str, request) -> dict:
    """卖家资金流水页：明细 / 按日 / 入金 / 少收 / 告警（同一总流水）。"""
    from .cash_manage_helpers import build_cash_month_choices, resolve_cash_month

    get = getattr(request, 'GET', {}) or {}
    tab = (get.get('tab') or 'all').strip()
    valid_tabs = {code for code, _ in FUND_LEDGER_TABS}
    if tab not in valid_tabs:
        tab = 'all'

    view = (get.get('view') or 'detail').strip()
    valid_views = {code for code, _ in FUND_LEDGER_VIEWS}
    if view not in valid_views:
        view = 'detail'

    q = (get.get('q') or '').strip()
    date_from = (get.get('date_from') or '').strip()
    date_to = (get.get('date_to') or '').strip()
    fl_month = resolve_cash_month(get.get('fl_month'))

    order_alerts = detect_fund_ledger_order_alerts(seller_id)
    alert_order_count = len(order_alerts)

    ctx: dict[str, Any] = {
        'fund_ledger_tab': tab,
        'fund_ledger_tabs': FUND_LEDGER_TABS,
        'fund_ledger_view': view,
        'fund_ledger_views': FUND_LEDGER_VIEWS,
        'fund_ledger_q': q,
        'fund_ledger_date_from': date_from,
        'fund_ledger_date_to': date_to,
        'fund_ledger_fl_month': fl_month,
        'fund_ledger_month_choices': build_cash_month_choices(
            selected=fl_month, extra_months=[fl_month] if fl_month else [],
        ),
        'fund_ledger_alert_order_count': alert_order_count,
        'fund_ledger_daily': None,
        'fund_ledger_entries': [],
        'fund_ledger_empty': True,
    }

    if view == 'daily':
        daily = build_fund_ledger_daily_summary(
            seller_id, year_month=fl_month, payment_method=tab,
        )
        ctx['fund_ledger_daily'] = daily
        ctx['fund_ledger_empty'] = not daily['rows']
        return ctx

    qs = (
        FundLedgerEntry.objects.filter(seller_id=seller_id)
        .select_related('buy_order')
        .order_by('-occurred_at', '-ledger_id')
    )
    if tab != 'all':
        qs = qs.filter(payment_method=tab)

    if view == 'remit':
        qs = qs.filter(business_type='cash_remittance_confirmed')
    elif view == 'shortfall':
        qs = qs.filter(business_type='cash_exception_settled')
    elif view == 'alerts':
        if order_alerts:
            qs = qs.filter(buy_order_id__in=list(order_alerts.keys()))
        else:
            qs = qs.none()

    start_at = _parse_ledger_day(date_from, end_of_day=False)
    end_at = _parse_ledger_day(date_to, end_of_day=True)
    if start_at:
        qs = qs.filter(occurred_at__gte=start_at)
    if end_at:
        qs = qs.filter(occurred_at__lte=end_at)

    qs = _apply_fund_ledger_search(qs, q)

    entries = []
    for row in qs[:300]:
        order_key = str(row.buy_order_id) if row.buy_order_id else ''
        flags = list(order_alerts.get(order_key, []))
        entries.append(entry_display_row(row, alert_flags=flags))

    ctx['fund_ledger_entries'] = entries
    ctx['fund_ledger_empty'] = not entries
    return ctx
