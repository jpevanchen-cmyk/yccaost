# 进度 84 · 现金管理框架：共用数据组装（工作台 Tab + 卖家后台分区）



from __future__ import annotations



from collections import defaultdict

from decimal import Decimal, ROUND_HALF_UP





def _money2(value) -> Decimal:

    """金额统一保留两位小数。"""

    return Decimal(value or 0).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)





def resolve_cash_month(raw_value) -> str:

    """解析 YYYY-MM；默认当前北京月份。"""

    import re

    from django.utils import timezone

    from .time_helpers import to_beijing

    default = to_beijing(timezone.now()).date().strftime('%Y-%m')

    text = (raw_value or '').strip()

    matched = re.match(r'^(\d{4})-(\d{1,2})$', text)

    if matched:

        year_num = int(matched.group(1))

        month_num = int(matched.group(2))

        if 1900 <= year_num <= 2100 and 1 <= month_num <= 12:

            return f'{year_num:04d}-{month_num:02d}'

    return default





def build_cash_month_choices(*, selected: str, extra_months: list[str] | None = None) -> list[dict]:

    """月份下拉：最近 12 个月 + 有数据的月份。"""

    from datetime import date



    from django.utils import timezone



    from .time_helpers import to_beijing



    today = to_beijing(timezone.now()).date()

    months: list[str] = []

    year = today.year

    month = today.month

    for _ in range(12):

        months.append(f'{year:04d}-{month:02d}')

        month -= 1

        if month == 0:

            month = 12

            year -= 1

    for item in extra_months or []:

        if item and item not in months:

            months.append(item)

    months = sorted(set(months), reverse=True)

    labels = []

    for ym in months:

        year_num, month_num = ym.split('-')

        labels.append({

            'value': ym,

            'label': f'{year_num}年{int(month_num)}月',

            'selected': ym == selected,

        })

    return labels





def query_cash_exception_orders(seller_id: str, *, limit: int = 30):

    """货到付款少收/异常单（管理人员处理）。"""

    from .models import BuyOrder



    return list(

        BuyOrder.objects.filter(

            seller_id=seller_id,

            cash_shortfall_status__in=(

                'buyer_pending', 'buyer_rejected', 'exception',

            ),

        ).select_related('delivery_order').order_by('updated_at')[:limit]

    )





def query_pending_cash_remittances(seller_id: str, *, limit: int = 30):

    """待核对配送员交款申请。"""

    from .rider_cash_helpers import pending_remittance_requests



    return list(pending_remittance_requests(seller_id)[:limit])





def build_cash_manage_daily_table(

    seller_id: str,

    *,

    year_month: str | None = None,

    max_rows: int = 60,

) -> dict:

    """

    按北京日期汇总货到付款现金（表格 + 合计行）。

    year_month 形如 2026-08 时只返回该月各行。

    """

    from .models import CashRemittanceRequest

    from .plugins.fulfillment.rider_cash_helpers import _cod_cash_qs

    from .time_helpers import to_beijing



    bucket: dict[str, dict] = defaultdict(lambda: {

        'pending_count': 0,

        'pending_amount': Decimal('0'),

        'remitted_amount': Decimal('0'),

        'daily_total': Decimal('0'),

    })



    for order in _cod_cash_qs(seller_id).only(

        'cash_collected_at', 'cash_remitted_at', 'cash_collected_amount',

    ).iterator():

        amount = order.cash_collected_amount or Decimal('0')

        if order.cash_collected_at:

            collect_day = to_beijing(order.cash_collected_at).date().isoformat()

            bucket[collect_day]['daily_total'] += amount

            if order.cash_remitted_at is None:

                bucket[collect_day]['pending_count'] += 1

                bucket[collect_day]['pending_amount'] += amount

        if order.cash_remitted_at:

            remit_day = to_beijing(order.cash_remitted_at).date().isoformat()

            bucket[remit_day]['remitted_amount'] += amount



    pending_req_count = CashRemittanceRequest.objects.filter(

        seller_id=seller_id, status='pending',

    ).count()

    pending_note = ''

    if pending_req_count:

        pending_note = f'当前有 {pending_req_count} 笔交款申请待核对'



    month_prefix = (year_month or '').strip()

    sorted_days = sorted(bucket.keys(), reverse=True)

    if month_prefix:

        sorted_days = [day for day in sorted_days if day.startswith(month_prefix)]

    sorted_days = sorted_days[:max_rows]



    rows = []

    for idx, day in enumerate(sorted_days):

        data = bucket[day]

        rows.append({

            'date': day,

            'pending_count': data['pending_count'],

            'pending_amount': _money2(data['pending_amount']),

            'remitted_amount': _money2(data['remitted_amount']),

            'daily_total': _money2(data['daily_total']),

            'note': pending_note if idx == 0 and pending_note else '',

        })



    totals = {

        'pending_count': sum(row['pending_count'] for row in rows),

        'pending_amount': _money2(sum((row['pending_amount'] for row in rows), Decimal('0'))),

        'remitted_amount': _money2(sum((row['remitted_amount'] for row in rows), Decimal('0'))),

        'daily_total': _money2(sum((row['daily_total'] for row in rows), Decimal('0'))),

    }

    return {'rows': rows, 'totals': totals, 'year_month': month_prefix}





def _attach_cash_manage_daily(ctx: dict, seller_id: str, *, request=None) -> None:

    """卖家后台 / 工作台共用：挂上日汇总表与月份选择。"""

    month = resolve_cash_month(request.GET.get('cash_month') if request else None)

    table = build_cash_manage_daily_table(seller_id, year_month=month)

    ctx['cash_month'] = month

    ctx['cash_daily_table'] = table

    ctx['cash_month_choices'] = build_cash_month_choices(

        selected=month,

        extra_months=[month] if month else [],

    )





def build_workbench_cash_manage_context(

    seller_id: str,

    *,

    work_user,

    request=None,

) -> dict:

    """店铺工作台 · 现金管理 Tab。"""

    from .staff_account_helpers import PERM_FULFILLMENT_CASH_MANAGE, staff_has_permission



    can_manage = (

        work_user.role == 'seller'

        or staff_has_permission(work_user, PERM_FULFILLMENT_CASH_MANAGE)

    )

    ctx = {

        'cash_manage_allowed': can_manage,

        'cash_exception_orders': [],

        'pending_cash_remittances': [],

        'cash_manage_empty': True,

    }

    if not can_manage:

        ctx['cash_manage_readonly_hint'] = (

            '👀 您没有「现金异常与入金处理」权限，无法在此操作。'

        )

        return ctx



    exceptions = query_cash_exception_orders(seller_id)

    remittances = query_pending_cash_remittances(seller_id)

    ctx['cash_exception_orders'] = exceptions

    ctx['pending_cash_remittances'] = remittances

    _attach_cash_manage_daily(ctx, seller_id, request=request)

    ctx['cash_manage_no_pending_actions'] = not exceptions and not remittances

    ctx['cash_manage_empty'] = (

        ctx['cash_manage_no_pending_actions']

        and not ctx['cash_daily_table']['rows']

    )

    ctx['cash_fold_daily_open'] = bool(ctx['cash_daily_table']['rows']) or not exceptions and not remittances

    ctx['cash_fold_exception_open'] = bool(exceptions)

    ctx['cash_fold_remittance_open'] = bool(remittances) and not exceptions

    return ctx





def build_seller_cash_manage_context(seller_id: str, *, request=None) -> dict:

    """卖家后台 · 现金管理分区（仅店主）。"""

    from .forms import ShopBossRemittanceNotifyForm

    from .operating_helpers import get_operating_settings

    from .order_notify_ui_helpers import smtp_not_ready_message

    from .plugin_runtime.registry import is_plugin_enabled



    fulfillment_on = is_plugin_enabled('fulfillment', seller_id)

    ctx = {

        'fulfillment_enabled': fulfillment_on,

        'cash_exception_orders': query_cash_exception_orders(seller_id) if fulfillment_on else [],

        'pending_cash_remittances': query_pending_cash_remittances(seller_id) if fulfillment_on else [],

        'can_use_remittance_alert': fulfillment_on,

    }

    if fulfillment_on:

        operating = get_operating_settings(seller_id)

        ctx['boss_remittance_notify_form'] = ShopBossRemittanceNotifyForm(instance=operating)

        ctx['boss_remittance_notify_smtp_warn'] = smtp_not_ready_message(

            operating.boss_remittance_notify_enabled,

        )

        _attach_cash_manage_daily(ctx, seller_id, request=request)

        exceptions = ctx['cash_exception_orders']

        remittances = ctx['pending_cash_remittances']

        ctx['cash_manage_no_pending_actions'] = not exceptions and not remittances

        ctx['cash_fold_daily_open'] = bool(ctx['cash_daily_table']['rows']) or ctx['cash_manage_no_pending_actions']

        ctx['cash_fold_exception_open'] = bool(exceptions)

        ctx['cash_fold_remittance_open'] = bool(remittances) and not exceptions

    return ctx

