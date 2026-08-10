# 订单取消：客人未备货可取消；店家取消须权限 + 沟通门槛 + 操作留痕

from django.db import transaction
from django.utils import timezone
from .time_helpers import now_local_wall

from .models import BuyOrder, OrderMessage
from .order_status_transition_helpers import (
    BUYER_SELF_CANCELABLE_STATUSES,
    buyer_can_self_cancel_order,
    transition_order_status,
)
from .shop_work_helpers import current_seller_id_for_user

# 客人仍可自主取消的状态（§5.6.8 已迁至 order_status_transition_helpers.BUYER_SELF_CANCELABLE_STATUSES）
BUYER_CANCELABLE_STATUSES = ()  # 兼容旧引用，勿再使用

# 店家仍可兜底取消的状态（已完成 / 已取消除外）
SHOP_CANCELABLE_STATUSES = (
    'awaiting_payment',
    'awaiting_shop_confirm',
    'awaiting_prep',
    'preparing',
    'ready_pickup',
    'delivering',
)

BUYER_BLOCKED_HINT = '当前订单进度已无法自主取消订单，请联系商家协商。'
SHOP_NOTE_MIN_LEN = 8


def resolve_employer_seller_id(user) -> str | None:
    """当前账号所属店铺卖家 ID（店主为自己，员工为雇主）"""
    return current_seller_id_for_user(user) or None


def user_has_cancel_order_perm(user) -> bool:
    """是否有权执行店家侧取消（店主始终可以；员工须勾选权限）"""
    if not user or not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    from .staff_account_helpers import PERM_CANCEL_ORDER, staff_has_permission

    return staff_has_permission(user, PERM_CANCEL_ORDER)


def buyer_can_self_cancel(order: BuyOrder) -> bool:
    return buyer_can_self_cancel_order(order)


def buyer_cancel_blocked_hint(order: BuyOrder) -> str:
    if order.order_status == 'cancelled':
        return '订单已取消'
    if order.order_status in ('completed',):
        return BUYER_BLOCKED_HINT
    if order.order_status not in BUYER_SELF_CANCELABLE_STATUSES:
        return BUYER_BLOCKED_HINT
    return ''


def shop_can_cancel_order(user, order: BuyOrder) -> bool:
    if order.order_status not in SHOP_CANCELABLE_STATUSES:
        return False
    seller_id = resolve_employer_seller_id(user)
    if not seller_id or seller_id != order.seller_id:
        return False
    if not user_has_cancel_order_perm(user):
        return False
    # V1：已微信到账单仅店主可取消（会触发原路退款）
    if order.payment_status == 'paid' and order.payment_method == 'wechat':
        return getattr(user, 'role', '') == 'seller'
    return True


def shop_has_cancel_communication(order: BuyOrder) -> bool:
    """沟通区是否已有留言历史"""
    return order.messages.exists()


def shop_cancel_gate_ok(order: BuyOrder, note: str) -> tuple[bool, str]:
    """店家取消门槛：已有沟通，或本次写明沟通过程"""
    if shop_has_cancel_communication(order):
        return True, ''
    text = (note or '').strip()
    if len(text) < SHOP_NOTE_MIN_LEN:
        return False, (
            f'取消前须在订单沟通中留有记录，或在下方写明与客人的沟通方式与过程'
            f'（至少 {SHOP_NOTE_MIN_LEN} 个字）'
        )
    return True, ''


def _cancel_delivery_if_any(order: BuyOrder) -> None:
    delivery = getattr(order, 'delivery_order', None)
    if not delivery:
        return
    if delivery.delivery_status == 'cancelled':
        return
    delivery.delivery_status = 'cancelled'
    delivery.save(update_fields=['delivery_status', 'updated_at'])


def _apply_cancel_fields(order: BuyOrder, *, side: str, note: str) -> list[str]:
    now = now_local_wall()
    transition_order_status(
        order, 'cancelled', source='order_cancel_helpers._apply_cancel_fields',
    )
    order.cancelled_at = now
    order.cancel_side = side
    order.cancel_note = (note or '').strip()[:500]
    fields = ['order_status', 'cancelled_at', 'cancel_side', 'cancel_note', 'updated_at']
    if order.payment_status == 'pending_payment':
        order.payment_status = 'cancelled'
        fields.append('payment_status')
    return fields


@transaction.atomic
def cancel_order_by_buyer(order: BuyOrder, user) -> tuple[bool, str]:
    """买家自主取消"""
    if user.role != 'buyer' or order.buyer_id != user.username:
        return False, '只能取消自己的订单'
    if not buyer_can_self_cancel(order):
        return False, BUYER_BLOCKED_HINT

    fields = _apply_cancel_fields(order, side='buyer', note='买家自主取消')
    order.save(update_fields=fields)
    from .menu_helpers import release_catalog_sales_for_order

    release_catalog_sales_for_order(order)
    _cancel_delivery_if_any(order)

    from .audit_helpers import write_audit_log

    write_audit_log(
        action_code='order_status',
        action_label='买家取消订单',
        seller_id=order.seller_id,
        actor=user,
        target_type='order',
        target_id=str(order.order_id),
        summary=f'买家取消订单 {order.get_display_order_no()}',
    )
    return True, '订单已取消'


@transaction.atomic
def cancel_order_by_shop(order: BuyOrder, user, note: str = '') -> tuple[bool, str]:
    """店家/授权员工取消（兜底）"""
    if not shop_can_cancel_order(user, order):
        if (
            order.payment_status == 'paid'
            and order.payment_method == 'wechat'
            and user_has_cancel_order_perm(user)
            and resolve_employer_seller_id(user) == order.seller_id
            and getattr(user, 'role', '') != 'seller'
        ):
            return False, '已微信收款的订单只能由店主取消并原路退款，请联系店主'
        return False, '您没有取消此订单的权限，或订单已不可取消'

    ok, gate_msg = shop_cancel_gate_ok(order, note)
    if not ok:
        return False, gate_msg

    refund_msg = ''
    from .payments.service import get_payment_settings
    from .payments.wechat_refund_helpers import (
        get_wechat_success_record,
        initiate_wechat_refund_for_order,
        order_needs_wechat_refund,
    )

    cancel_at = now_local_wall()
    if order_needs_wechat_refund(order):
        pay_settings = get_payment_settings(order.seller_id)
        refund_ok, refund_msg = initiate_wechat_refund_for_order(
            order,
            pay_settings,
            operator=getattr(user, 'username', '') or 'seller',
        )
        if not refund_ok:
            return False, refund_msg
        record = get_wechat_success_record(order)
        if record:
            from .fund_ledger_hooks import record_shop_order_cancelled_wechat_refund

            record_shop_order_cancelled_wechat_refund(
                order,
                out_trade_no=record.out_trade_no,
                source='shop_cancel_refund',
                operator=getattr(user, 'username', '') or 'seller',
                occurred_at=cancel_at,
            )

    text = (note or '').strip()
    # 若本次填写了沟通备注且沟通区尚无记录，写入一条店家留言留痕
    if text and not shop_has_cancel_communication(order):
        OrderMessage.objects.create(
            order=order,
            author_side='shop',
            author_username=user.username,
            body=f'【取消前沟通】{text}'[:300],
        )

    reason = text or '店家取消（沟通区已有记录）'
    fields = _apply_cancel_fields(order, side='shop', note=reason)
    order.save(update_fields=fields)
    from .menu_helpers import release_catalog_sales_for_order

    release_catalog_sales_for_order(order)
    _cancel_delivery_if_any(order)

    order.refresh_from_db()

    from .audit_helpers import write_audit_log

    paid_hint = ''
    if order.payment_status == 'paid' and order.payment_method == 'wechat':
        paid_hint = f'；微信退款：{refund_msg or "已提交"}'
    elif order.payment_status == 'paid':
        paid_hint = '；若已收款请线下退款给客人'
    write_audit_log(
        action_code='order_status',
        action_label='店家取消订单',
        seller_id=order.seller_id,
        actor=user,
        target_type='order',
        target_id=str(order.order_id),
        summary=f'店家取消订单 {order.get_display_order_no()}：{reason[:200]}{paid_hint}',
    )
    msg = '订单已取消'
    if order.payment_status == 'refunded':
        msg += '，微信款已原路退回'
    elif order.payment_status == 'paid' and order.payment_method == 'wechat':
        msg += f'。{refund_msg or "微信退款已提交，请稍后在订单页查看结果"}'
    elif order.payment_status == 'paid':
        msg += '。若已收款，请尽快线下退款给客人'
    return True, msg
