# 履约包：外卖货到付款 — 配送员现金统计与入金确认

from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from waimai.models import (
    BuyOrder,
    CashRemittanceItem,
    CashRemittanceRequest,
)


def _cod_cash_qs(seller_id: str):
    """本店外卖货到付款、且配送员已收现金的订单。"""
    return BuyOrder.objects.filter(
        seller_id=seller_id,
        fulfillment_type='delivery',
        payment_method='cash',
        cash_collected_at__isnull=False,
    )


def rider_cash_summary(seller_id: str) -> dict:
    """
    店主/店长看的现金入金汇总：
    - riders：每人「已收未交」的单数与金额（供确认入金）
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
        'pending_requests': list(pending_remittance_requests(seller_id)[:30]),
    }


def pending_remit_orders_for_rider(seller_id: str, rider_id: str):
    """某配送员「已收未交」的现金单（供入金确认）。"""
    return _cod_cash_qs(seller_id).filter(
        cash_collected_by=rider_id,
        cash_remitted_at__isnull=True,
    )


def rider_available_remit_orders(seller_id: str, rider_id: str):
    """配送员可放进新交款申请的订单；待审核申请中的订单不能重复申请。"""
    return (
        pending_remit_orders_for_rider(seller_id, rider_id)
        .filter(payment_status='paid', order_status='completed')
        .exclude(cash_remittance_items__request__status='pending')
        .distinct()
        .order_by('cash_collected_at')
    )


@transaction.atomic
def create_cash_remittance_request(
    seller_id: str, rider_id: str, note: str = '',
) -> tuple[CashRemittanceRequest | None, str]:
    """把该配送员当前可交的现金订单合成一张申请。"""
    orders = list(rider_available_remit_orders(seller_id, rider_id).select_for_update())
    if not orders:
        return None, '当前没有可发起交款的现金订单'
    total = sum((order.cash_collected_amount or Decimal('0') for order in orders), Decimal('0'))
    request = CashRemittanceRequest.objects.create(
        seller_id=seller_id,
        rider_id=rider_id,
        total_amount=total,
        order_count=len(orders),
        note=(note or '').strip(),
    )
    CashRemittanceItem.objects.bulk_create([
        CashRemittanceItem(
            request=request,
            order=order,
            amount=order.cash_collected_amount or Decimal('0'),
        )
        for order in orders
    ])
    return request, f'已发起交款申请：{len(orders)} 单，共 ¥{total}'


def rider_remittance_context(seller_id: str, rider_id: str) -> dict:
    """配送员页面的可申请金额与近期交款记录。"""
    available = rider_available_remit_orders(seller_id, rider_id)
    agg = available.aggregate(cnt=Count('order_id'), amount=Sum('cash_collected_amount'))
    return {
        'available_count': agg['cnt'] or 0,
        'available_total': agg['amount'] or Decimal('0'),
        'requests': list(
            CashRemittanceRequest.objects.filter(
                seller_id=seller_id, rider_id=rider_id,
            ).order_by('-created_at')[:10]
        ),
    }


def pending_remittance_requests(seller_id: str):
    """店主或有权限管理人员待核对的交款申请。"""
    return (
        CashRemittanceRequest.objects.filter(seller_id=seller_id, status='pending')
        .prefetch_related('items__order')
        .order_by('created_at')
    )


@transaction.atomic
def review_cash_remittance_request(
    seller_id: str,
    request_id,
    reviewer_id: str,
    *,
    approve: bool,
    note: str = '',
) -> tuple[bool, str]:
    """管理人员确认或退回一张配送员交款申请。"""
    try:
        remit = CashRemittanceRequest.objects.select_for_update().get(
            request_id=request_id, seller_id=seller_id,
        )
    except CashRemittanceRequest.DoesNotExist:
        return False, '交款申请不存在'
    if remit.status != 'pending':
        return False, '这张交款申请已经处理，不能重复操作'

    review_note = (note or '').strip()
    now = timezone.now()
    if not approve:
        if len(review_note) < 2:
            return False, '退回时请填写原因（至少两个字）'
        remit.status = 'rejected'
        remit.reviewed_by = reviewer_id or ''
        remit.review_note = review_note
        remit.reviewed_at = now
        remit.save(update_fields=[
            'status', 'reviewed_by', 'review_note', 'reviewed_at', 'updated_at',
        ])
        return True, '已退回交款申请，配送员可修改说明后重新发起'

    order_ids = list(remit.items.values_list('order_id', flat=True))
    orders = list(BuyOrder.objects.select_for_update().filter(order_id__in=order_ids))
    invalid = [order for order in orders if not order.cash_remit_pending()]
    if invalid:
        return False, '申请内有订单已入金或状态变化，请核对后重试'
    from waimai.payments import confirm_cash_remittance

    count, _ = confirm_cash_remittance(orders, reviewer_id)
    if count != remit.order_count:
        return False, '本次确认笔数与申请不一致，未完成入金'
    remit.status = 'confirmed'
    remit.reviewed_by = reviewer_id or ''
    remit.review_note = review_note
    remit.reviewed_at = now
    remit.save(update_fields=[
        'status', 'reviewed_by', 'review_note', 'reviewed_at', 'updated_at',
    ])
    return True, f'已确认 {count} 笔现金入金，共 ¥{remit.total_amount}'
