# 主体交易通道门面
# 饮食插件开启时交给堂食/打包/外卖；停用时回落到主体「下单」通道。

from __future__ import annotations

from decimal import Decimal

CHANNEL_ORDER = 'order'
CHANNEL_DELIVERY = 'delivery'
CHANNEL_TAKEAWAY = 'takeaway'
CHANNEL_DINE_IN = 'dine_in'

ALL_CHANNELS = (
    CHANNEL_ORDER,
    CHANNEL_DELIVERY,
    CHANNEL_TAKEAWAY,
    CHANNEL_DINE_IN,
)


def _dining_enabled(seller_id: str) -> bool:
    from .plugin_runtime.registry import is_plugin_enabled

    return is_plugin_enabled('dining', seller_id)


def dining_plugin_enabled(seller_id: str) -> bool:
    """页面与其它主体模块读取饮食插件状态的稳定入口。"""
    return _dining_enabled(seller_id)


def _dining():
    from .plugins.dining import channel_helpers

    return channel_helpers


def channel_label(channel: str) -> str:
    if channel == CHANNEL_ORDER:
        return '下单'
    return _dining().channel_label(channel)


def needs_delivery_fields(channel: str) -> bool:
    return channel == CHANNEL_DELIVERY


def is_in_store_channel(channel: str) -> bool:
    return channel in (CHANNEL_TAKEAWAY, CHANNEL_DINE_IN)


def channel_session_key(seller_id: str) -> str:
    return f'shop_channel_{seller_id}'


def get_shop_channel(session, seller_id: str) -> str:
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
    """按店铺插件状态解析当前通道，并清掉不再有效的旧选择。"""
    if _dining_enabled(seller_id):
        return _dining().resolve_shop_channel(request, seller_id, table_session)

    selected = get_shop_channel(request.session, seller_id)
    if selected in (CHANNEL_DELIVERY, CHANNEL_TAKEAWAY, CHANNEL_DINE_IN):
        clear_shop_channel(request.session, seller_id)
        return ''
    return selected if selected == CHANNEL_ORDER else ''


def channel_switch_enabled(settings, channel: str) -> bool:
    if channel == CHANNEL_ORDER:
        return True
    return _dining().channel_switch_enabled(settings, channel)


def list_homepage_channels(seller_id: str) -> list[dict]:
    if _dining_enabled(seller_id):
        return _dining().list_homepage_channels(seller_id)

    from .operating_helpers import check_order_admission

    ok, msg = check_order_admission(seller_id, CHANNEL_ORDER)
    return [{
        'code': CHANNEL_ORDER,
        'label': '下单',
        'available': ok,
        'reason': '' if ok else msg,
    }]


def try_set_homepage_channel(
    request, seller_id: str, channel: str, table_session,
) -> tuple[bool, str]:
    if _dining_enabled(seller_id):
        return _dining().try_set_homepage_channel(
            request, seller_id, channel, table_session,
        )

    if (channel or '').strip() != CHANNEL_ORDER:
        return False, '当前店铺只提供「下单」通道'

    from .operating_helpers import check_order_admission

    ok, msg = check_order_admission(seller_id, CHANNEL_ORDER)
    if not ok:
        return False, msg
    set_shop_channel(request.session, seller_id, CHANNEL_ORDER)
    return True, ''


def require_shop_channel(request, seller_id: str, table_session) -> tuple[str, str]:
    if _dining_enabled(seller_id):
        return _dining().require_shop_channel(request, seller_id, table_session)

    channel = resolve_shop_channel(request, seller_id, None)
    if channel != CHANNEL_ORDER:
        return '', '请先选择「下单」后再挑选商品'
    return CHANNEL_ORDER, ''


def build_address_and_distance(
    request_post, shop_profile, channel: str,
) -> tuple[str, float]:
    if channel == CHANNEL_ORDER:
        return '【下单】由店家按商品说明或沟通约定处理', 0
    return _dining().build_address_and_distance(
        request_post, shop_profile, channel,
    )


def validate_place_order_channel(
    request, seller_id: str, posted_type: str, table_session,
) -> tuple[str, str]:
    if _dining_enabled(seller_id):
        return _dining().validate_place_order_channel(
            request, seller_id, posted_type, table_session,
        )

    selected = resolve_shop_channel(request, seller_id, None)
    if selected != CHANNEL_ORDER:
        return '', '请先选择「下单」'
    if (posted_type or '').strip() != CHANNEL_ORDER:
        return '', '下单通道已变化，请返回店铺重新确认'
    return CHANNEL_ORDER, ''


def build_order_pricing(
    seller_id, subtotal, distance_km, fulfillment_type,
):
    """主体通道不收配送费；饮食通道沿用原价格规则。"""
    if fulfillment_type == CHANNEL_ORDER:
        return Decimal('0.00'), {
            'lines': ['基础下单通道，不收配送费'],
            'fulfillment': CHANNEL_ORDER,
        }
    from .order_helpers import build_order_pricing as legacy_pricing

    return legacy_pricing(seller_id, subtotal, distance_km, fulfillment_type)


def channel_template_flags(channel: str) -> dict:
    return {
        'shop_channel': channel,
        'shop_channel_label': channel_label(channel),
        'needs_delivery_fields': needs_delivery_fields(channel),
        'is_in_store_channel': is_in_store_channel(channel),
        'is_basic_order_channel': channel == CHANNEL_ORDER,
    }
