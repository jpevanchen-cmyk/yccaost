"""配送员入金申请提醒：轮询计数与权限口径。"""

from __future__ import annotations


def query_pending_remittance_requests(seller_id: str):
    """待核对入金申请（与订单台、支付页同一口径）。"""
    from .rider_cash_helpers import pending_remittance_requests

    return pending_remittance_requests(seller_id)


def remittance_alert_snapshot(seller_id: str) -> tuple[int, int]:
    """返回 (待处理申请数, 最新申请时间戳毫秒)。"""
    qs = query_pending_remittance_requests(seller_id)
    count = qs.count()
    latest = qs.order_by('-created_at').values_list('created_at', flat=True).first()
    latest_ts = int(latest.timestamp() * 1000) if latest else 0
    return count, latest_ts


def work_user_can_use_remittance_alert(work_user) -> bool:
    """工作台：店主或有现金管理权限的员工可收入金提醒。"""
    if work_user is None:
        return False
    if getattr(work_user, 'role', '') == 'seller':
        return True
    from .staff_account_helpers import PERM_FULFILLMENT_CASH_MANAGE, staff_has_permission

    return staff_has_permission(work_user, PERM_FULFILLMENT_CASH_MANAGE)
