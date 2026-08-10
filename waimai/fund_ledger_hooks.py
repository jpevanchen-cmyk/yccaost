# 84a · 资金总流水写入点（挂到支付/现金业务）

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone
from .time_helpers import now_local_wall

from .fund_ledger_helpers import (
    record_fund_ledger_if_absent,
    transition_fund_ledger_entry,
    find_ledger_by_reference,
)
from .models import BuyOrder, FundLedgerEntry


def _order_amount(order: BuyOrder) -> Decimal:
    if order.cash_collected_amount is not None and order.payment_method == 'cash':
        return order.cash_collected_amount
    return order.total_amount


def record_payment_method_selected(
    order: BuyOrder,
    payment_method: str,
    *,
    source: str,
    operator: str = 'buyer',
) -> None:
    """买家选定支付方式（尚未到账）。"""
    record_fund_ledger_if_absent(
        order,
        reference_key=f'pay_method:{order.order_id}:{payment_method}',
        direction=FundLedgerEntry.DIRECTION_INCOME,
        amount=order.total_amount,
        payment_method=payment_method,
        business_type='payment_method_selected',
        source=source,
        operator=operator,
        entry_status=FundLedgerEntry.ENTRY_STATUS_SUCCESS,
        fund_status=FundLedgerEntry.FUND_STATUS_NOT_APPLICABLE,
    )


def record_order_payment_received(
    order: BuyOrder,
    payment_method: str,
    *,
    source: str,
    operator: str = 'system',
    amount=None,
    fund_status: str = FundLedgerEntry.FUND_STATUS_AT_SHOP,
    note: str = '',
) -> None:
    """在线/店内确认收款到账。"""
    method = payment_method or order.payment_method or 'cash'
    record_fund_ledger_if_absent(
        order,
        reference_key=f'paid:{order.order_id}:{method}',
        direction=FundLedgerEntry.DIRECTION_INCOME,
        amount=amount if amount is not None else order.total_amount,
        payment_method=method,
        business_type='demo_payment_success' if method == 'wechat_simulate' else 'payment_received',
        source=source,
        operator=operator,
        entry_status=FundLedgerEntry.ENTRY_STATUS_SUCCESS,
        fund_status=fund_status,
        note=note,
        occurred_at=order.payment_time or now_local_wall(),
    )


def record_wechat_scan_initiated(
    order: BuyOrder,
    *,
    out_trade_no: str,
    source: str = 'buyer_pay_page',
    operator: str = 'buyer',
) -> None:
    """发起微信扫码。"""
    record_fund_ledger_if_absent(
        order,
        reference_key=f'wechat_init:{out_trade_no}',
        direction=FundLedgerEntry.DIRECTION_INCOME,
        amount=order.total_amount,
        payment_method='wechat',
        business_type='wechat_scan_initiated',
        source=source,
        operator=operator,
        entry_status=FundLedgerEntry.ENTRY_STATUS_PENDING,
        fund_status=FundLedgerEntry.FUND_STATUS_PENDING_ARRIVAL,
    )


def record_wechat_payment_success(
    order: BuyOrder,
    *,
    out_trade_no: str,
    source: str = 'wechat_notify',
    operator: str = 'system',
) -> None:
    """微信通知/查单到账：更新发起行或新建成功行。"""
    init_ledger = find_ledger_by_reference(order.seller_id, f'wechat_init:{out_trade_no}')
    if init_ledger:
        transition_fund_ledger_entry(
            init_ledger,
            entry_status=FundLedgerEntry.ENTRY_STATUS_SUCCESS,
            fund_status=FundLedgerEntry.FUND_STATUS_AT_SHOP,
            operator=operator,
            source=source,
            note='微信到账',
        )
    record_fund_ledger_if_absent(
        order,
        reference_key=f'wechat_paid:{out_trade_no}',
        direction=FundLedgerEntry.DIRECTION_INCOME,
        amount=order.total_amount,
        payment_method='wechat',
        business_type='wechat_payment_success',
        source=source,
        operator=operator,
        entry_status=FundLedgerEntry.ENTRY_STATUS_SUCCESS,
        fund_status=FundLedgerEntry.FUND_STATUS_AT_SHOP,
        related_ledger=init_ledger,
        occurred_at=order.payment_time or now_local_wall(),
    )


def record_shop_order_cancelled_wechat_refund(
    order: BuyOrder,
    *,
    out_trade_no: str,
    source: str = 'shop_cancel_refund',
    operator: str = 'seller',
    occurred_at=None,
    note: str = '',
) -> None:
    """店家取消订单并发起微信原路退款（取消与发起退款合并记一条）。"""
    paid_ledger = find_ledger_by_reference(order.seller_id, f'wechat_paid:{out_trade_no}')
    record_fund_ledger_if_absent(
        order,
        reference_key=f'shop_cancel_refund:{order.order_id}',
        direction=FundLedgerEntry.DIRECTION_EXPENSE,
        amount=order.total_amount,
        payment_method='wechat',
        business_type='shop_order_cancelled',
        source=source,
        operator=operator,
        entry_status=FundLedgerEntry.ENTRY_STATUS_SUCCESS,
        fund_status='',
        related_ledger=paid_ledger,
        note=note or '店家取消订单并发起微信原路退款',
        occurred_at=occurred_at or now_local_wall(),
    )


def record_wechat_refund_processing(
    order: BuyOrder,
    *,
    out_refund_no: str,
    out_trade_no: str,
    source: str = 'shop_cancel_refund',
    operator: str = 'seller',
) -> None:
    """发起微信退款：记一条支出流水（处理中）。"""
    paid_ledger = find_ledger_by_reference(order.seller_id, f'wechat_paid:{out_trade_no}')
    record_fund_ledger_if_absent(
        order,
        reference_key=f'wechat_refund:{out_refund_no}',
        direction=FundLedgerEntry.DIRECTION_EXPENSE,
        amount=order.total_amount,
        payment_method='wechat',
        business_type='wechat_refund_processing',
        source=source,
        operator=operator,
        entry_status=FundLedgerEntry.ENTRY_STATUS_PENDING,
        fund_status='',
        refund_status=FundLedgerEntry.REFUND_STATUS_PROCESSING,
        related_ledger=paid_ledger,
        note='微信原路退款处理中',
    )


def record_wechat_refund_success(
    order: BuyOrder,
    *,
    out_refund_no: str,
    out_trade_no: str,
    source: str = 'wechat_refund_query',
    operator: str = 'system',
) -> None:
    """微信退款到账：结束处理中行，并另记一条退款完成流水。"""
    refund_ledger = find_ledger_by_reference(order.seller_id, f'wechat_refund:{out_refund_no}')
    paid_ledger = find_ledger_by_reference(order.seller_id, f'wechat_paid:{out_trade_no}')
    if refund_ledger:
        transition_fund_ledger_entry(
            refund_ledger,
            entry_status=FundLedgerEntry.ENTRY_STATUS_SUCCESS,
            refund_status=FundLedgerEntry.REFUND_STATUS_COMPLETED,
            operator=operator,
            source=source,
            note='微信原路退款完成',
        )
    record_fund_ledger_if_absent(
        order,
        reference_key=f'wechat_refund_done:{out_refund_no}',
        direction=FundLedgerEntry.DIRECTION_EXPENSE,
        amount=order.total_amount,
        payment_method='wechat',
        business_type='wechat_refund_success',
        source=source,
        operator=operator,
        entry_status=FundLedgerEntry.ENTRY_STATUS_SUCCESS,
        fund_status='',
        refund_status=FundLedgerEntry.REFUND_STATUS_COMPLETED,
        related_ledger=refund_ledger or paid_ledger,
        note='微信原路退款完成',
        occurred_at=now_local_wall(),
    )


def record_rider_cash_collected(
    order: BuyOrder,
    rider_id: str,
    *,
    source: str = 'rider_delivery_panel',
) -> None:
    """骑手送达收现金：钱在骑手手中（在途）。"""
    record_fund_ledger_if_absent(
        order,
        reference_key=f'rider_collect:{order.order_id}',
        direction=FundLedgerEntry.DIRECTION_INCOME,
        amount=_order_amount(order),
        payment_method='cash',
        business_type='rider_cash_collected',
        source=source,
        operator=rider_id or 'rider',
        entry_status=FundLedgerEntry.ENTRY_STATUS_SUCCESS,
        fund_status=FundLedgerEntry.FUND_STATUS_IN_TRANSIT,
        note=order.cash_shortfall_reason or '',
        occurred_at=order.cash_collected_at or now_local_wall(),
    )


def record_cash_remittance_confirmed(
    order: BuyOrder,
    confirmer_id: str,
    *,
    source: str = 'cash_manage_panel',
) -> None:
    """店主确认骑手交款入店。"""
    collect_ledger = find_ledger_by_reference(order.seller_id, f'rider_collect:{order.order_id}')
    if collect_ledger:
        transition_fund_ledger_entry(
            collect_ledger,
            fund_status=FundLedgerEntry.FUND_STATUS_AT_SHOP,
            operator=confirmer_id,
            source=source,
            note='入金确认',
        )
    record_fund_ledger_if_absent(
        order,
        reference_key=f'remit:{order.order_id}',
        direction=FundLedgerEntry.DIRECTION_INCOME,
        amount=_order_amount(order),
        payment_method='cash',
        business_type='cash_remittance_confirmed',
        source=source,
        operator=confirmer_id or 'manager',
        entry_status=FundLedgerEntry.ENTRY_STATUS_SUCCESS,
        fund_status=FundLedgerEntry.FUND_STATUS_AT_SHOP,
        related_ledger=collect_ledger,
        occurred_at=order.cash_remitted_at or now_local_wall(),
    )


def record_cash_exception_settled(
    order: BuyOrder,
    manager_id: str,
    *,
    source: str,
    note: str = '',
) -> None:
    """管理人员少收兜底结单。"""
    record_fund_ledger_if_absent(
        order,
        reference_key=f'cash_exception:{order.order_id}',
        direction=FundLedgerEntry.DIRECTION_INCOME,
        amount=_order_amount(order),
        payment_method='cash',
        business_type='cash_exception_settled',
        source=source,
        operator=manager_id or 'manager',
        entry_status=FundLedgerEntry.ENTRY_STATUS_SUCCESS,
        fund_status=FundLedgerEntry.FUND_STATUS_IN_TRANSIT,
        note=note,
        occurred_at=order.payment_time or now_local_wall(),
    )
