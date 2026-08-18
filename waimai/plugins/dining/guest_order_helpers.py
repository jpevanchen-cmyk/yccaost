# 饮食插件：堂食游客免登录下单——归属校验、现场付落地、结账翻台清会话

from waimai.models import BuyOrder, TableSession

from .table_helpers import close_table_session
from .wait_time_helpers import assign_default_wait_time


def is_guest_order(order: BuyOrder) -> bool:
    """没有买家账号的订单，视为游客单（靠桌台会话归属）。"""
    return not (getattr(order, 'buyer_id', None) or '').strip()


def normalize_guest_nickname(raw: str) -> str:
    """可选称呼：去掉首尾空格，最长 20 字；空则返回空串。"""
    return (raw or '').strip()[:20]


def resolve_order_buyer_id(request) -> str:
    """已登录且具备买家资格用账号名（含已开店的店主）；游客返回空串。"""
    from waimai.account_helpers import user_has_buyer_capability

    user = getattr(request, 'user', None)
    if user_has_buyer_capability(user):
        return user.username
    return ''


def guest_can_access_order(request, order: BuyOrder, table_sess: TableSession | None) -> bool:
    """
    游客本机能否看/处理该单：
    - 必须是堂食游客单
    - 当前浏览器持有本店「进行中」的桌台会话
    - 订单挂在同一会话上
    结账/翻台关掉会话后，本机即不可再靠会话看见（投诉以店内小票为准）。
    """
    if not is_guest_order(order):
        return False
    if not order.is_dine_in():
        return False
    if not table_sess or getattr(table_sess, 'status', '') != 'open':
        return False
    if not order.table_session_id:
        return False
    return str(order.table_session_id) == str(table_sess.session_id)


def buyer_or_guest_can_access_order(request, order: BuyOrder, table_sess: TableSession | None = None) -> bool:
    """已登录客人认账号（含已开店的店主）；游客认桌台会话。"""
    from waimai.account_helpers import eco_is_order_buyer

    user = getattr(request, 'user', None)
    if eco_is_order_buyer(user, order):
        return True
    return guest_can_access_order(request, order, table_sess)


def apply_guest_onsite_cash(order: BuyOrder) -> tuple[bool, list[str]]:
    """游客堂食现场付现金：占清单名额后进入待备货。"""
    from waimai.menu_helpers import try_apply_catalog_sales_for_order

    ok, errors = try_apply_catalog_sales_for_order(order)
    if not ok:
        return False, errors

    order.payment_method = 'cash'
    from waimai.order_status_transition_helpers import transition_order_status

    transition_order_status(
        order, 'awaiting_prep', source='guest_order_helpers.apply_guest_onsite_cash',
    )
    assign_default_wait_time(order, save=False)
    order.save(update_fields=[
        'payment_method', 'order_status', 'estimated_ready_at', 'updated_at',
    ])
    from waimai.order_alert_helpers import maybe_notify_merchant_new_order

    maybe_notify_merchant_new_order(order)
    return True, []


def maybe_close_table_session_after_settle(order: BuyOrder) -> None:
    """堂食单结账完成（或未收款结案）后关闭桌台会话，相当于翻台。"""
    if not order.is_dine_in():
        return
    if order.order_status != 'completed':
        return
    session = getattr(order, 'table_session', None)
    if session is None and order.table_session_id:
        session = TableSession.objects.filter(session_id=order.table_session_id).first()
    if session is None:
        return
    if session.status == 'open':
        close_table_session(session)
