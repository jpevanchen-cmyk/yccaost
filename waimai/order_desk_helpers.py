# 主体通用订单台：处理基础「下单」通道，不依赖饮食插件。

from __future__ import annotations

from django.utils import timezone

from .models import BuyOrder

# 主体订单台可推进的履约状态
ACTIVE_BASIC_STATUSES = (
    'awaiting_prep',
    'preparing',
    'ready_pickup',
)


def basic_order_can_start(order: BuyOrder) -> bool:
    """是否可「开始处理」。"""
    return (
        order.is_basic_order()
        and order.order_status == 'awaiting_prep'
        and order.payment_status in ('paid', 'pending_payment')
    )


def basic_order_can_mark_ready(order: BuyOrder) -> bool:
    """是否可「标记可交付」。"""
    return order.is_basic_order() and order.order_status == 'preparing'


def basic_order_can_complete(order: BuyOrder) -> bool:
    """是否可「确认完成」（现金须先确认收款）。"""
    if not order.is_basic_order() or order.order_status != 'ready_pickup':
        return False
    if order.payment_method == 'cash' and order.payment_status == 'pending_payment':
        return False
    return order.payment_status == 'paid'


def basic_order_can_confirm_cash(order: BuyOrder) -> bool:
    """基础下单现金单是否可确认收款。"""
    return (
        order.is_basic_order()
        and order.payment_method == 'cash'
        and order.payment_status == 'pending_payment'
        and order.order_status in ACTIVE_BASIC_STATUSES
    )


def start_basic_order(order: BuyOrder, *, actor) -> tuple[bool, str]:
    """待备货 → 处理中。"""
    if not basic_order_can_start(order):
        return False, '当前订单不能开始处理'
    now = timezone.now()
    order.order_status = 'preparing'
    order.preparing_at = now
    order.save(update_fields=['order_status', 'preparing_at', 'updated_at'])
    from .audit_helpers import audit_order_status

    audit_order_status(
        order=order,
        actor=actor,
        summary=f'开始处理基础订单 {order.get_display_order_no()}',
    )
    return True, '已开始处理该订单'


def mark_basic_order_ready(order: BuyOrder, *, actor) -> tuple[bool, str]:
    """处理中 → 可交付。"""
    if not basic_order_can_mark_ready(order):
        return False, '当前订单不能标记为可交付'
    order.order_status = 'ready_pickup'
    order.ready_at = timezone.now()
    order.save(update_fields=['order_status', 'ready_at', 'updated_at'])
    from .audit_helpers import audit_order_status

    audit_order_status(
        order=order,
        actor=actor,
        summary=f'标记可交付 {order.get_display_order_no()}',
    )
    return True, '已标记为可交付'


def complete_basic_order(order: BuyOrder, *, actor) -> tuple[bool, str]:
    """可交付 → 已完成。"""
    if not basic_order_can_complete(order):
        if (
            order.is_basic_order()
            and order.order_status == 'ready_pickup'
            and order.payment_method == 'cash'
            and order.payment_status == 'pending_payment'
        ):
            return False, '请先确认已收到现金，再完成订单'
        return False, '当前订单不能确认完成'
    order.order_status = 'completed'
    order.save(update_fields=['order_status', 'updated_at'])
    from .audit_helpers import audit_order_status

    audit_order_status(
        order=order,
        actor=actor,
        summary=f'完成基础订单 {order.get_display_order_no()}',
    )
    return True, '订单已完成'


def confirm_basic_order_cash(order: BuyOrder, *, actor) -> tuple[bool, str]:
    """确认基础下单现金已收（只改支付状态，不回退履约进度）。"""
    if not basic_order_can_confirm_cash(order):
        return False, '该订单不是待确认的现金单'
    from .audit_helpers import audit_order_status
    from .payments.core import mark_payment_received

    newly = mark_payment_received(order, 'cash')
    if not newly:
        return False, '该订单已收款，无需重复确认'
    audit_order_status(
        order=order,
        actor=actor,
        summary=f'确认现金收款 {order.get_display_order_no()}',
    )
    return True, '已确认收款'


def build_order_desk_context(seller_id: str, *, work_user, sort_mode: str = 'newest') -> dict:
    """组装通用订单台页面数据。"""
    from .staff_account_helpers import (
        PERM_FULFILLMENT_CASH_MANAGE,
        PERM_ORDERS_CONFIRM_PAYMENT,
        PERM_ORDERS_CONTACT,
        PERM_ORDERS_UPDATE_STATUS,
        PERM_ORDERS_VIEW,
        staff_has_permission,
    )

    can_view = staff_has_permission(work_user, PERM_ORDERS_VIEW)
    can_update = staff_has_permission(work_user, PERM_ORDERS_UPDATE_STATUS)
    can_confirm = staff_has_permission(work_user, PERM_ORDERS_CONFIRM_PAYMENT)
    can_contact = staff_has_permission(work_user, PERM_ORDERS_CONTACT)
    can_cash_manage = staff_has_permission(work_user, PERM_FULFILLMENT_CASH_MANAGE)

    from .workbench_sort_helpers import order_queryset_by_created

    orders = list(
        order_queryset_by_created(
            BuyOrder.objects.filter(
                seller_id=seller_id,
                fulfillment_type='order',
                order_status__in=ACTIVE_BASIC_STATUSES,
            ),
            sort_mode,
        )[:50]
    )

    rows = []
    for order in orders:
        rows.append({
            'order': order,
            'can_start': can_update and basic_order_can_start(order),
            'can_mark_ready': can_update and basic_order_can_mark_ready(order),
            'can_complete': can_update and basic_order_can_complete(order),
            'can_confirm_cash': can_confirm and basic_order_can_confirm_cash(order),
            'needs_cash_before_complete': (
                order.order_status == 'ready_pickup'
                and order.payment_method == 'cash'
                and order.payment_status == 'pending_payment'
            ),
        })

    cash_exceptions = []
    pending_remittances = []
    if can_cash_manage:
        cash_exceptions = list(
            BuyOrder.objects.filter(
                seller_id=seller_id,
                cash_shortfall_status__in=(
                    'buyer_pending', 'buyer_rejected', 'exception',
                ),
            ).select_related('delivery_order').order_by('updated_at')[:30]
        )
        from .rider_cash_helpers import pending_remittance_requests

        pending_remittances = list(pending_remittance_requests(seller_id)[:30])

    return {
        'order_desk_rows': rows,
        'order_desk_can_view': can_view,
        'order_desk_can_update': can_update,
        'order_desk_can_confirm': can_confirm,
        'order_desk_can_contact': can_contact,
        'order_desk_empty': not rows,
        'cash_manage_allowed': can_cash_manage,
        'cash_exception_orders': cash_exceptions,
        'pending_cash_remittances': pending_remittances,
    }
