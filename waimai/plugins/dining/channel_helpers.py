# 饮食插件：店铺下单通道（外卖 / 打包 / 堂食）——会话 + 准入 + 共用规则
# 堂食只能扫桌码等现场入口；主页进店只可选外卖/打包。

from __future__ import annotations

from waimai.order_helpers import parse_distance_km, store_delivery_address

CHANNEL_DELIVERY = 'delivery'
CHANNEL_TAKEAWAY = 'takeaway'
CHANNEL_DINE_IN = 'dine_in'

ALL_CHANNELS = (CHANNEL_DELIVERY, CHANNEL_TAKEAWAY, CHANNEL_DINE_IN)

CHANNEL_LABELS = {
    CHANNEL_DELIVERY: '外卖',
    CHANNEL_TAKEAWAY: '打包',
    CHANNEL_DINE_IN: '堂食',
}

# 普通主页进店可选（堂食只能扫桌码等现场入口）
HOMEPAGE_PICKABLE_CHANNELS = (CHANNEL_DELIVERY, CHANNEL_TAKEAWAY)

# 到店类：不要配送地址/距离
IN_STORE_CHANNELS = frozenset({CHANNEL_TAKEAWAY, CHANNEL_DINE_IN})


def channel_label(channel: str) -> str:
    return CHANNEL_LABELS.get(channel, channel or '')


def needs_delivery_fields(channel: str) -> bool:
    """是否需要客人填送达地址与距离（仅外卖）。"""
    return channel == CHANNEL_DELIVERY


def is_in_store_channel(channel: str) -> bool:
    """堂食或打包：到店履约，不收配送费。"""
    return channel in IN_STORE_CHANNELS


def channel_session_key(seller_id: str) -> str:
    return f'shop_channel_{seller_id}'


def get_shop_channel(session, seller_id: str) -> str:
    """读取本店当前所选通道；无效则空串。"""
    raw = (session.get(channel_session_key(seller_id)) or '').strip()
    if raw in ALL_CHANNELS:
        return raw
    return ''


def set_shop_channel(session, seller_id: str, channel: str) -> None:
    session[channel_session_key(seller_id)] = channel
    session.modified = True


def clear_shop_channel(session, seller_id: str) -> None:
    session.pop(channel_session_key(seller_id), None)
    session.modified = True


def resolve_shop_channel(request, seller_id: str, table_session) -> str:
    """
    解析当前通道：
    - 有桌台会话 → 强制堂食
    - 否则用会话里客人自选的外卖/打包（无桌台却记着堂食则清空）
    """
    if table_session:
        set_shop_channel(request.session, seller_id, CHANNEL_DINE_IN)
        return CHANNEL_DINE_IN
    ch = get_shop_channel(request.session, seller_id)
    if ch == CHANNEL_DINE_IN:
        clear_shop_channel(request.session, seller_id)
        return ''
    return ch


def channel_switch_enabled(settings, channel: str) -> bool:
    """店主后台「当前是否允许该通道接单」开关。"""
    if channel == CHANNEL_DELIVERY:
        return bool(settings.delivery_channel_enabled)
    if channel == CHANNEL_TAKEAWAY:
        return bool(getattr(settings, 'takeaway_channel_enabled', True))
    if channel == CHANNEL_DINE_IN:
        return bool(settings.dine_channel_enabled)
    return False


def list_homepage_channels(seller_id: str) -> list[dict]:
    """主页进店可选通道列表（统一结构，循环生成，不写死两套分支页面逻辑）。"""
    from waimai.operating_helpers import check_order_admission, get_operating_settings

    settings = get_operating_settings(seller_id)
    options = []
    for code in HOMEPAGE_PICKABLE_CHANNELS:
        if not channel_switch_enabled(settings, code):
            continue
        ok, msg = check_order_admission(seller_id, code)
        options.append({
            'code': code,
            'label': f'{channel_label(code)}' + ('配送' if code == CHANNEL_DELIVERY else '自取'),
            'available': ok,
            'reason': '' if ok else msg,
        })
    return options


def try_set_homepage_channel(request, seller_id: str, channel: str, table_session) -> tuple[bool, str]:
    """
    客人自选通道。成功返回 (True, '')；失败返回 (False, 白话原因)。
    桌台会话下只能堂食，不能改成外卖/打包。
    """
    from waimai.operating_helpers import check_order_admission

    if table_session:
        set_shop_channel(request.session, seller_id, CHANNEL_DINE_IN)
        return True, ''
    ch = (channel or '').strip()
    if ch not in HOMEPAGE_PICKABLE_CHANNELS:
        return False, '请选择外卖或打包。堂食请扫桌上的二维码进入。'
    ok, msg = check_order_admission(seller_id, ch)
    if not ok:
        return False, msg
    set_shop_channel(request.session, seller_id, ch)
    return True, ''


def require_shop_channel(request, seller_id: str, table_session) -> tuple[str, str]:
    """
    点菜/结算前必须已有通道。
    返回 (channel, error)；error 非空表示不能继续。
    """
    ch = resolve_shop_channel(request, seller_id, table_session)
    if not ch:
        return '', '请先选择外卖或打包通道后再点菜。'
    if ch == CHANNEL_DINE_IN and not table_session:
        return '', '堂食请扫桌上的二维码进入，不能从普通进店下单。'
    return ch, ''


def build_address_and_distance(request_post, shop_profile, channel: str) -> tuple[str, float]:
    """按通道统一准备送达/取餐地址与距离（各通道共用，不写三套）。"""
    if is_in_store_channel(channel):
        return store_delivery_address(shop_profile, channel), 0
    address = (request_post.get('delivery_address') or '默认地址').strip() or '默认地址'
    return address, parse_distance_km(request_post.get('distance_km'))


def validate_place_order_channel(request, seller_id: str, posted_type: str, table_session) -> tuple[str, str]:
    """
    正式下单时锁定通道：须与会话一致；堂食须桌台；禁止主页串堂食。
    返回 (fulfillment_type, error)。
    """
    from waimai.order_helpers import parse_fulfillment_type

    session_ch = resolve_shop_channel(request, seller_id, table_session)
    posted = parse_fulfillment_type(posted_type)

    if table_session:
        return CHANNEL_DINE_IN, ''

    if not session_ch:
        return '', '请先选择外卖或打包通道。'
    if session_ch == CHANNEL_DINE_IN:
        return '', '堂食请扫桌上的二维码进入。'
    # 以会话为准，忽略页面篡改
    if posted and posted != session_ch and posted in HOMEPAGE_PICKABLE_CHANNELS:
        # 仍以会话为准
        pass
    return session_ch, ''


def channel_template_flags(channel: str) -> dict:
    """模板用开关，避免模板里写一堆 if 通道名。"""
    return {
        'shop_channel': channel,
        'shop_channel_label': channel_label(channel),
        'needs_delivery_fields': needs_delivery_fields(channel),
        'is_in_store_channel': is_in_store_channel(channel),
    }
