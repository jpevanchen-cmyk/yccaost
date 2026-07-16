# 订单取消：客人未备货可取消；店家取消须权限 + 沟通门槛 + 操作留痕

from django.db import transaction
from django.utils import timezone

from .models import BuyOrder, OrderMessage
from .shop_work_helpers import SHOP_STAFF_ROLES

# 客人仍可自主取消的状态（尚未开始备货）
BUYER_CANCELABLE_STATUSES = (
    'awaiting_payment',
    'awaiting_shop_confirm',
    'awaiting_prep',
)

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
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    if user.role == 'seller':
        return user.username
    if user.role in SHOP_STAFF_ROLES:
        return (user.employer_seller_id or '').strip() or None
    return None


def user_has_cancel_order_perm(user) -> bool:
    """是否有权执行店家侧取消（店主始终可以；员工须勾选权限）"""
    if not user or not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    if user.role == 'seller':
        return True
    if user.role in SHOP_STAFF_ROLES:
        return bool(getattr(user, 'perm_cancel_order', False))
    return False


def buyer_can_self_cancel(order: BuyOrder) -> bool:
    if order.order_status == 'cancelled':
        return False
    return order.order_status in BUYER_CANCELABLE_STATUSES


def buyer_cancel_blocked_hint(order: BuyOrder) -> str:
    if order.order_status == 'cancelled':
        return '订单已取消'
    if order.order_status in ('completed',):
        return BUYER_BLOCKED_HINT
    if order.order_status not in BUYER_CANCELABLE_STATUSES:
        return BUYER_BLOCKED_HINT
    return ''


def shop_can_cancel_order(user, order: BuyOrder) -> bool:
    if order.order_status not in SHOP_CANCELABLE_STATUSES:
        return False
    seller_id = resolve_employer_seller_id(user)
    if not seller_id or seller_id != order.seller_id:
        return False
    return user_has_cancel_order_perm(user)


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
    now = timezone.now()
    order.order_status = 'cancelled'
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
        return False, '您没有取消此订单的权限，或订单已不可取消'

    ok, gate_msg = shop_cancel_gate_ok(order, note)
    if not ok:
        return False, gate_msg

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
    _cancel_delivery_if_any(order)

    from .audit_helpers import write_audit_log

    paid_hint = ''
    if order.payment_status == 'paid':
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
    if order.payment_status == 'paid':
        msg += '。若已收款，请尽快线下退款给客人'
    return True, msg
