# A.11.1 营业时间与接单准入

from django.utils import timezone

from .models import ShopOperatingSettings


def get_operating_settings(seller_id: str) -> ShopOperatingSettings:
    """获取店铺营业设置，没有则创建默认"""
    settings, _ = ShopOperatingSettings.objects.get_or_create(seller_id=seller_id)
    return settings


def _in_time_window(now_t, start_t, end_t) -> bool:
    """判断当前时刻是否在时段内（支持跨午夜）"""
    if start_t <= end_t:
        return start_t <= now_t <= end_t
    return now_t >= start_t or now_t <= end_t


def _channel_window(settings: ShopOperatingSettings, channel: str):
    """取渠道接单时段，未单独设置则用全天营业时段"""
    if channel == 'dine':
        if settings.dine_open and settings.dine_close:
            return settings.dine_open, settings.dine_close
    elif channel == 'delivery':
        if settings.delivery_open and settings.delivery_close:
            return settings.delivery_open, settings.delivery_close
    return settings.business_open, settings.business_close


def check_order_admission(seller_id: str, fulfillment_type: str) -> tuple[bool, str]:
    """
    新单准入（A.11.1）：须同时满足全天营业、渠道时段、渠道开关、未打烊、未暂停。
    fulfillment_type: delivery / dine_in / takeaway
    """
    settings = get_operating_settings(seller_id)
    now_t = timezone.localtime(timezone.now()).time()

    if settings.pause_new_orders:
        return False, '店铺已暂停接单，请稍后再试'
    if settings.closed_for_today:
        return False, '店铺本日已打烊，暂不接新单'
    if not _in_time_window(now_t, settings.business_open, settings.business_close):
        return False, '当前不在营业时间内'

    if fulfillment_type == 'delivery':
        if not settings.delivery_channel_enabled:
            return False, '外卖接单已关闭'
        start_t, end_t = _channel_window(settings, 'delivery')
        if not _in_time_window(now_t, start_t, end_t):
            return False, '当前不在外卖接单时段内'
    else:
        if not settings.dine_channel_enabled:
            return False, '堂食/打包接单已关闭'
        start_t, end_t = _channel_window(settings, 'dine')
        if not _in_time_window(now_t, start_t, end_t):
            return False, '当前不在堂食接单时段内'

    return True, ''


def has_open_orders(seller_id: str) -> bool:
    """是否有未结束订单（切换菜单清单前检查）"""
    from .models import BuyOrder
    return BuyOrder.objects.filter(
        seller_id=seller_id,
    ).exclude(order_status__in=('completed', 'cancelled')).exists()
