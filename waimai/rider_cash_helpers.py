# 外卖货到付款：骑手现金统计与入金确认（批次 B）

from decimal import Decimal

from django.db.models import Count, Q, Sum

from .models import BuyOrder


def _cod_cash_qs(seller_id: str):
    """本店外卖货到付款、且骑手已收现金的订单。"""
    return BuyOrder.objects.filter(
        seller_id=seller_id,
        fulfillment_type='delivery',
        payment_method='cash',
        cash_collected_at__isnull=False,
    )


def rider_cash_summary(seller_id: str) -> dict:
    """
    店主/店长看的现金入金汇总：
    - riders：每名骑手「已收未交」的单数与金额（供确认入金）
    - remitted_total / remitted_count：已入金累计
    - pending_total / pending_count：待入金累计
    """
    qs = _cod_cash_qs(seller_id)

    pending = qs.filter(cash_remitted_at__isnull=True)
    remitted = qs.filter(cash_remitted_at__isnull=False)

    riders = []
    rider_rows = (
        pending.values('cash_collected_by')
        .annotate(cnt=Count('order_id'), amount=Sum('cash_collected_amount'))
        .order_by('-amount')
    )
    for row in rider_rows:
        riders.append({
            'rider_id': row['cash_collected_by'] or '(未知)',
            'count': row['cnt'],
            'amount': row['amount'] or Decimal('0'),
        })

    pending_agg = pending.aggregate(cnt=Count('order_id'), amount=Sum('cash_collected_amount'))
    remitted_agg = remitted.aggregate(cnt=Count('order_id'), amount=Sum('cash_collected_amount'))

    return {
        'riders': riders,
        'pending_count': pending_agg['cnt'] or 0,
        'pending_total': pending_agg['amount'] or Decimal('0'),
        'remitted_count': remitted_agg['cnt'] or 0,
        'remitted_total': remitted_agg['amount'] or Decimal('0'),
    }


def pending_remit_orders_for_rider(seller_id: str, rider_id: str):
    """某骑手「已收未交」的现金单（供入金确认）。"""
    return _cod_cash_qs(seller_id).filter(
        cash_collected_by=rider_id,
        cash_remitted_at__isnull=True,
    )
