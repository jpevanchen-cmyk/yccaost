# A.11.1 营业时间与接单准入

from __future__ import annotations

import re
from urllib.parse import urlparse

from django.utils import timezone

from .models import ShopOperatingSettings


def get_operating_settings(seller_id: str) -> ShopOperatingSettings:
    """获取店铺营业设置，没有则创建默认"""
    settings, _ = ShopOperatingSettings.objects.get_or_create(seller_id=seller_id)
    return settings


def parse_table_lan_url(raw: str) -> dict:
    """
    把已保存的桌码局域网地址拆成填写界面用的几块。
    返回：mode(ip/name)、ip1～ip4、port、hostname。
    """
    empty = {
        'mode': 'ip',
        'ip1': '', 'ip2': '', 'ip3': '', 'ip4': '',
        'port': '8000',
        'hostname': '',
    }
    text = (raw or '').strip().rstrip('/')
    if not text:
        return empty

    # 没有协议时补上，方便解析
    if '://' not in text:
        text = 'http://' + text
    try:
        parsed = urlparse(text)
    except Exception:
        return empty

    host = (parsed.hostname or '').strip()
    port = parsed.port
    if not host:
        return empty

    # 纯数字四段 → IP 模式
    if re.fullmatch(r'\d{1,3}(?:\.\d{1,3}){3}', host):
        parts = host.split('.')
        return {
            'mode': 'ip',
            'ip1': parts[0],
            'ip2': parts[1],
            'ip3': parts[2],
            'ip4': parts[3],
            'port': str(port) if port else '8000',
            'hostname': '',
        }

    return {
        'mode': 'name',
        'ip1': '', 'ip2': '', 'ip3': '', 'ip4': '',
        'port': str(port) if port else '8000',
        'hostname': host,
    }


def assemble_table_lan_url(
    *,
    mode: str,
    ip1='', ip2='', ip3='', ip4='',
    port='',
    hostname='',
) -> tuple[str, str]:
    """
    拼装桌码局域网根地址。成功返回 (url, '')；失败返回 ('', 白话错误)。
    协议固定 http://；端口可空（空则默认 8000）。
    """
    mode = (mode or 'ip').strip()
    port_raw = (str(port) if port is not None else '').strip()
    if port_raw == '':
        port_num = 8000
    else:
        if not port_raw.isdigit():
            return '', '端口须填写数字'
        port_num = int(port_raw)
        if port_num < 1 or port_num > 65535:
            return '', '端口须在 1～65535 之间'

    if mode == 'name':
        host = (hostname or '').strip().rstrip('/')
        if not host:
            return '', ''  # 清空
        if '://' in host or '/' in host or ' ' in host:
            return '', '店内固定名字只需填主机名，例如 yecao.local，不要带 http:// 或斜杠'
        if re.fullmatch(r'\d{1,3}(?:\.\d{1,3}){3}', host):
            return '', '数字地址请改用「四段数字」填写，不要填在固定名字里'
        return f'http://{host}:{port_num}', ''

    # IP 模式
    parts = [(ip1 or '').strip(), (ip2 or '').strip(), (ip3 or '').strip(), (ip4 or '').strip()]
    if all(p == '' for p in parts):
        return '', ''  # 清空
    if any(p == '' for p in parts):
        return '', '四段数字须全部填齐，或全部留空表示不设局域网地址'
    nums = []
    for p in parts:
        if not p.isdigit():
            return '', '四段地址只能填数字'
        n = int(p)
        if n < 0 or n > 255:
            return '', '每一段数字须在 0～255 之间'
        nums.append(str(n))
    return f'http://{".".join(nums)}:{port_num}', ''


def build_order_alert_config(seller_id: str) -> dict:
    """给新单强提醒前端用的店铺自定义配置：音量(0~1)、重复间隔(秒)、自定义音频网址。"""
    settings = get_operating_settings(seller_id)
    volume = int(getattr(settings, 'alert_volume', 60) or 0)
    volume = max(0, min(100, volume)) / 100.0
    interval = int(getattr(settings, 'alert_interval_sec', 8) or 8)
    if interval < 3:
        interval = 3
    sound_url = ''
    sound = getattr(settings, 'alert_sound', None)
    if sound:
        try:
            sound_url = sound.url
        except Exception:
            sound_url = ''
    return {'volume': volume, 'interval': interval, 'sound_url': sound_url}


def _in_time_window(now_t, start_t, end_t) -> bool:
    """判断当前时刻是否在时段内（支持跨午夜）"""
    if start_t <= end_t:
        return start_t <= now_t <= end_t
    return now_t >= start_t or now_t <= end_t


def _channel_window(settings: ShopOperatingSettings, channel: str):
    """取渠道接单时段，未单独设置则用全天营业时段。打包暂与堂食共用堂食时段。"""
    if channel in ('dine', 'takeaway'):
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
    from .channel_helpers import channel_label, channel_switch_enabled

    settings = get_operating_settings(seller_id)
    now_t = timezone.localtime(timezone.now()).time()

    if settings.pause_new_orders:
        return False, '店铺已暂停接单，请稍后再试'
    if settings.closed_for_today:
        return False, '店铺本日已打烊，暂不接新单'
    if not _in_time_window(now_t, settings.business_open, settings.business_close):
        return False, '当前不在营业时间内'

    # 通道开关与时段：统一查表，不按通道复制三套 if
    window_key = {
        'delivery': 'delivery',
        'takeaway': 'takeaway',
        'dine_in': 'dine',
    }.get(fulfillment_type)
    if not window_key:
        return False, '未知的取餐方式'
    if not channel_switch_enabled(settings, fulfillment_type):
        return False, f'{channel_label(fulfillment_type)}接单已关闭'

    start_t, end_t = _channel_window(settings, window_key)
    if not _in_time_window(now_t, start_t, end_t):
        return False, f'当前不在{channel_label(fulfillment_type)}接单时段内'
    return True, ''


def has_open_orders(seller_id: str) -> bool:
    """是否有未结束订单（切换菜单清单前检查）"""
    from .models import BuyOrder
    return BuyOrder.objects.filter(
        seller_id=seller_id,
    ).exclude(order_status__in=('completed', 'cancelled')).exists()
