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


def entry_display_row(entry: FundLedgerEntry) -> dict[str, str]:
    """模板用：一行流水的中文展示字段。"""
    order = entry.buy_order if entry.buy_order_id else None
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


def build_seller_fund_ledger_context(seller_id: str, request) -> dict:
    """卖家资金流水页：总表 + 支付方式 tab（同一数据源）。"""
    tab = (request.GET.get('tab') or 'all').strip()
    valid_tabs = {code for code, _ in FUND_LEDGER_TABS}
    if tab not in valid_tabs:
        tab = 'all'

    qs = (
        FundLedgerEntry.objects.filter(seller_id=seller_id)
        .select_related('buy_order')
        .order_by('-occurred_at', '-ledger_id')
    )
    if tab != 'all':
        qs = qs.filter(payment_method=tab)

    entries = [entry_display_row(row) for row in qs[:200]]
    return {
        'fund_ledger_tab': tab,
        'fund_ledger_tabs': FUND_LEDGER_TABS,
        'fund_ledger_entries': entries,
        'fund_ledger_empty': not entries,
    }
