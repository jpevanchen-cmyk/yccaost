"""三类订单共用的默认等待时间、分时段规则与单单调整。"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_time

from .models import BuyOrder, ShopWaitTimeRule
from .operating_helpers import get_operating_settings


WAIT_CHANNELS = ('dine_in', 'takeaway', 'delivery')
DEFAULT_FIELD_BY_CHANNEL = {
    'dine_in': 'dine_default_wait_minutes',
    'takeaway': 'takeaway_default_wait_minutes',
    'delivery': 'delivery_default_wait_minutes',
}


def _clamp_minutes(raw, default: int = 20) -> int:
    """等待时间统一限制为 1～240 分钟。"""
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        minutes = default
    return max(1, min(240, minutes))


def _time_in_window(now_t, start_t, end_t) -> bool:
    """判断时间是否进入分时段；支持跨午夜，结束点归下一时段。"""
    if start_t < end_t:
        return start_t <= now_t < end_t
    return now_t >= start_t or now_t < end_t


def resolve_wait_minutes(seller_id: str, channel: str, *, at=None) -> int:
    """按店铺、订单类型和当前时段，算出本单默认等待分钟数。"""
    settings = get_operating_settings(seller_id)
    field_name = DEFAULT_FIELD_BY_CHANNEL.get(channel, 'dine_default_wait_minutes')
    default_minutes = _clamp_minutes(getattr(settings, field_name, 20))
    moment = timezone.localtime(at or timezone.now())
    now_t = moment.time()
    for rule in settings.wait_time_rules.filter(channel=channel):
        if _time_in_window(now_t, rule.start_time, rule.end_time):
            return _clamp_minutes(rule.wait_minutes, default_minutes)
    return default_minutes


def assign_default_wait_time(order: BuyOrder, *, at=None, save: bool = True) -> int:
    """订单进入店铺处理队列时，自动写入预计完成时间。"""
    moment = at or timezone.now()
    minutes = resolve_wait_minutes(order.seller_id, order.fulfillment_type, at=moment)
    order.estimated_ready_at = moment + timedelta(minutes=minutes)
    if save:
        order.save(update_fields=['estimated_ready_at', 'updated_at'])
    return minutes


def can_adjust_order_wait_time(order: BuyOrder) -> bool:
    """服务员和后厨可调整仍在备货流程中的单。"""
    return order.order_status in (
        'awaiting_shop_confirm',
        'awaiting_prep',
        'preparing',
        'ready_pickup',
    )


def adjust_order_wait_time(order: BuyOrder, raw_minutes) -> tuple[bool, str, int]:
    """把单个订单改为从现在起再等若干分钟。"""
    if not can_adjust_order_wait_time(order):
        return False, '当前订单不能修改预计时间', 0
    try:
        minutes = int(raw_minutes)
    except (TypeError, ValueError):
        return False, '请输入正确的分钟数', 0
    if minutes < 1 or minutes > 240:
        return False, '等待时间须填写 1～240 分钟', 0
    order.estimated_ready_at = timezone.now() + timedelta(minutes=minutes)
    order.save(update_fields=['estimated_ready_at', 'updated_at'])
    return True, f'预计时间已改为从现在起约 {minutes} 分钟', minutes


def _segments(start_t, end_t) -> list[tuple[int, int]]:
    """把普通/跨午夜时段转成便于检查重叠的分钟区间。"""
    start = start_t.hour * 60 + start_t.minute
    end = end_t.hour * 60 + end_t.minute
    if start < end:
        return [(start, end)]
    return [(start, 24 * 60), (0, end)]


def parse_wait_time_rules(post_data) -> tuple[list[dict], str]:
    """读取营业设置页面中的多行分时段规则，并检查填写冲突。"""
    channels = post_data.getlist('wait_rule_channel')
    starts = post_data.getlist('wait_rule_start')
    ends = post_data.getlist('wait_rule_end')
    minutes_list = post_data.getlist('wait_rule_minutes')
    row_count = max(len(channels), len(starts), len(ends), len(minutes_list), 0)
    rows: list[dict] = []
    for index in range(row_count):
        channel = channels[index].strip() if index < len(channels) else ''
        start_raw = starts[index].strip() if index < len(starts) else ''
        end_raw = ends[index].strip() if index < len(ends) else ''
        minutes_raw = minutes_list[index].strip() if index < len(minutes_list) else ''
        if not any((channel, start_raw, end_raw, minutes_raw)):
            continue
        if channel not in WAIT_CHANNELS:
            return [], f'第 {index + 1} 行没有选择正确的订单类型'
        start_t = parse_time(start_raw)
        end_t = parse_time(end_raw)
        if not start_t or not end_t or start_t == end_t:
            return [], f'第 {index + 1} 行的开始、结束时间不正确'
        try:
            minutes = int(minutes_raw)
        except (TypeError, ValueError):
            return [], f'第 {index + 1} 行的等待分钟数不正确'
        if minutes < 1 or minutes > 240:
            return [], f'第 {index + 1} 行等待时间须为 1～240 分钟'
        rows.append({
            'channel': channel,
            'start_time': start_t,
            'end_time': end_t,
            'wait_minutes': minutes,
            'sort_order': index,
        })

    for channel in WAIT_CHANNELS:
        channel_rows = [row for row in rows if row['channel'] == channel]
        occupied: list[tuple[int, int]] = []
        for row in channel_rows:
            for start, end in _segments(row['start_time'], row['end_time']):
                if any(start < old_end and old_start < end for old_start, old_end in occupied):
                    return [], '同一种订单的分时段不能互相重叠'
                occupied.append((start, end))
    return rows, ''


@transaction.atomic
def replace_wait_time_rules(settings, rows: list[dict]) -> None:
    """保存时整体替换本店分时段规则，避免残留旧行。"""
    settings.wait_time_rules.all().delete()
    ShopWaitTimeRule.objects.bulk_create([
        ShopWaitTimeRule(settings=settings, **row)
        for row in rows
    ])
