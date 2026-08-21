# 饮食插件：游客免登录下单——堂食桌码归属、打包/外卖本单信息、现场付落地、结账翻台清会话

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from waimai.models import BuyOrder, TableSession

from .table_helpers import close_table_session
from .wait_time_helpers import assign_default_wait_time

# 本浏览器会话认领的游客打包/外卖单（只存订单号，不存姓名电话）
SESSION_GUEST_ORDER_IDS = 'guest_claimed_order_ids'
_PHONE_RE = re.compile(r'^[\d+\-\s()]{6,20}$')


def is_guest_order(order: BuyOrder) -> bool:
    """没有买家账号的订单，视为游客单。"""
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


def get_guest_checkout_switches(seller_id: str) -> dict:
    """读取店铺「未登录顾客」三开关；无营业设置行时按系统默认全关。"""
    from waimai.dine_models import ShopOperatingSettings

    row = ShopOperatingSettings.objects.filter(seller_id=seller_id).first()
    if not row:
        return {
            'takeaway': False,
            'delivery_online': False,
            'delivery_cod': False,
        }
    return {
        'takeaway': bool(row.guest_takeaway_enabled),
        'delivery_online': bool(row.guest_delivery_online_enabled),
        'delivery_cod': bool(row.guest_delivery_cod_enabled),
    }


def guest_remote_checkout_allowed(seller_id: str, fulfillment_type: str) -> tuple[bool, str]:
    """
    游客能否走打包/外卖结算（不认堂食桌码）。
    外卖须在线付或货到付款至少开一项；货到付款还须叠加店铺 A.5 总开关与履约插件。
    """
    from waimai.channel_helpers import CHANNEL_DELIVERY, CHANNEL_TAKEAWAY
    from waimai.payments.core import get_payment_settings
    from waimai.plugins.fulfillment.ownership import fulfillment_plugin_enabled

    switches = get_guest_checkout_switches(seller_id)
    channel = (fulfillment_type or '').strip()
    if channel == CHANNEL_TAKEAWAY:
        if switches['takeaway']:
            return True, ''
        return False, '本店暂未开放未登录打包下单，请先登录后再下单'

    if channel == CHANNEL_DELIVERY:
        online_ok = switches['delivery_online']
        cod_ok = False
        if switches['delivery_cod']:
            pay = get_payment_settings(seller_id)
            cod_ok = bool(
                fulfillment_plugin_enabled(seller_id)
                and getattr(pay, 'enable_cod', True)
            )
        if online_ok or cod_ok:
            return True, ''
        if switches['delivery_cod'] and not cod_ok:
            return False, '本店暂未开放未登录外卖下单（货到付款总开关未开），请先登录'
        return False, '本店暂未开放未登录外卖下单，请先登录后再下单'

    return False, '未登录仅可堂食扫桌码，或店铺已开放的打包/外卖通道'


def parse_guest_contact(request_post) -> tuple[dict | None, str]:
    """
    解析游客本单必要信息。姓名、电话必填；邮箱可选（不填则只能靠订单号核对）。
    返回 ({name, phone, email}, '') 或 (None, 人话错误)。
    """
    name = (request_post.get('guest_contact_name') or '').strip()[:40]
    phone = (request_post.get('guest_contact_phone') or '').strip()[:20]
    email = (request_post.get('guest_contact_email') or '').strip()[:254]

    if not name:
        return None, '请填写顾客姓名'
    if not phone:
        return None, '请填写顾客电话'
    if not _PHONE_RE.match(phone):
        return None, '顾客电话格式不正确，请核对后再填'

    if email:
        try:
            validate_email(email)
        except ValidationError:
            return None, '邮箱格式不正确；可不填，但请自行记下订单号'

    return {
        'name': name,
        'phone': phone,
        'email': email,
    }, ''


def claim_guest_order(request, order: BuyOrder) -> None:
    """下单成功后把本单记入浏览器会话，便于未登录继续支付/看单（不存姓名电话）。"""
    oid = str(order.order_id)
    claimed = list(request.session.get(SESSION_GUEST_ORDER_IDS) or [])
    if oid not in claimed:
        claimed.append(oid)
        # 只保留最近若干单，避免会话无限涨
        request.session[SESSION_GUEST_ORDER_IDS] = claimed[-20:]
        request.session.modified = True


def guest_session_can_access_order(request, order: BuyOrder) -> bool:
    """本浏览器会话是否认领过该游客打包/外卖单。"""
    if not is_guest_order(order):
        return False
    if order.is_dine_in():
        return False
    oid = str(order.order_id)
    claimed = request.session.get(SESSION_GUEST_ORDER_IDS) or []
    return oid in claimed


def guest_can_access_order(request, order: BuyOrder, table_sess: TableSession | None) -> bool:
    """
    游客本机能否看/处理该单：
    - 堂食：当前浏览器持有本店进行中桌台会话，且订单挂在同一会话
    - 打包/外卖：本浏览器会话认领过该单号（结账后仍可付/看本单）
    """
    if not is_guest_order(order):
        return False
    if order.is_dine_in():
        if not table_sess or getattr(table_sess, 'status', '') != 'open':
            return False
        if not order.table_session_id:
            return False
        return str(order.table_session_id) == str(table_sess.session_id)
    return guest_session_can_access_order(request, order)


def buyer_or_guest_can_access_order(request, order: BuyOrder, table_sess: TableSession | None = None) -> bool:
    """已登录客人认账号（含已开店的店主）；游客认桌台会话或本机认领的打包/外卖单。"""
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


def filter_guest_remote_pay_options(options: list, order: BuyOrder) -> list:
    """
    游客外卖：按店铺「在线付 / 货到付款」开关过滤支付方式。
    游客打包：不额外过滤（与已登录打包同一套可选方式）。
    """
    if not order or not is_guest_order(order):
        return options
    if getattr(order, 'fulfillment_type', '') != 'delivery':
        return options

    switches = get_guest_checkout_switches(order.seller_id)
    from waimai.payments.core import get_payment_settings
    from waimai.plugins.fulfillment.ownership import fulfillment_plugin_enabled

    online_ok = switches['delivery_online']
    cod_ok = bool(
        switches['delivery_cod']
        and fulfillment_plugin_enabled(order.seller_id)
        and getattr(get_payment_settings(order.seller_id), 'enable_cod', True)
    )
    filtered = []
    for opt in options:
        code = getattr(opt, 'code', '')
        if code == 'cash':
            if cod_ok:
                filtered.append(opt)
        else:
            if online_ok:
                filtered.append(opt)
    return filtered


def is_guest_remote_order(order: BuyOrder) -> bool:
    """游客打包/外卖单（非堂食桌码单）。"""
    if not order or not is_guest_order(order):
        return False
    return not order.is_dine_in()


def guest_order_voucher_url(order_id) -> str:
    """订单凭证页地址。"""
    from django.urls import reverse

    return reverse('guest_order_voucher', kwargs={'order_id': order_id})


def redirect_guest_remote_home(order: BuyOrder):
    """游客打包/外卖：付完或需回凭证时，回到订单凭证页。"""
    from django.shortcuts import redirect

    return redirect(guest_order_voucher_url(order.order_id))


def build_guest_order_voucher_context(request, order: BuyOrder) -> dict:
    """订单凭证页展示数据（只读）。"""
    from django.urls import reverse

    from waimai.email_helpers import is_email_ready
    from waimai.models import ShopProfile
    from waimai.order_alert_helpers import is_shop_new_order
    from waimai.order_helpers import dish_items_with_line_totals
    from waimai.order_shell_helpers import build_order_shell

    shop_profile = ShopProfile.objects.filter(seller_id=order.seller_id).first()
    shell = build_order_shell(order)
    dish_lines = dish_items_with_line_totals(order.dish_items)

    pending_pay = (
        order.payment_status == 'pending_payment'
        and order.order_status not in ('cancelled', 'completed')
    )
    show_cash_code = bool(
        pending_pay and (order.payment_method or '') == 'cash'
    )
    has_guest_email = bool((order.guest_contact_email or '').strip())
    # 与发信时机一致：在线已付，或已选现金/货到付款
    email_stage_ready = bool(has_guest_email and is_shop_new_order(order))

    return {
        'order': order,
        'order_shell': shell,
        'shop_profile': shop_profile,
        'dish_lines': dish_lines,
        'pending_pay': pending_pay,
        'show_cash_code': show_cash_code,
        'pay_url': reverse('pay_order', kwargs={'order_id': order.order_id}),
        'cash_code_url': reverse(
            'order_cash_code', kwargs={'order_id': order.order_id},
        ) if show_cash_code else '',
        'shop_url': f'/shop/?seller_id={order.seller_id}',
        'voucher_email_attempted': has_guest_email,
        'voucher_email_stage_ready': email_stage_ready,
        'voucher_email_ready': email_stage_ready and is_email_ready(),
    }
