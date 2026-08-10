# 全站时间出口：唯一允许做时区转换/本地墙钟处理的地方（§5.17 / 基础需求 5.5）
# 其它模块禁止直接调用 django.utils.timezone.localtime / localdate；
# 业务取「现在」请用 now_local_wall，禁止散落 timezone.now()。

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone

from wuwei_system.system_timezone import detect_system_timezone_name  # 再导出

_FALLBACK_TZ = 'Asia/Shanghai'

__all__ = [
    'detect_system_timezone_name',
    'get_active_zoneinfo',
    'ensure_local_aware',
    'to_local',
    'as_local',
    'as_storage_datetime',
    'format_local_time',
    'format_local',
    'format_local_iso',
    'now_local_wall',
    'local_today',
    'local_day_bounds_for_query',
    'local_day_start',
]


def get_active_zoneinfo() -> ZoneInfo:
    """当前 Django TIME_ZONE 对应的 ZoneInfo；异常时回落。"""
    name = getattr(settings, 'TIME_ZONE', None) or _FALLBACK_TZ
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo(_FALLBACK_TZ)


def ensure_local_aware(dt):
    """任意时间 → 系统时区 aware（naive 视为已是系统本地墙钟）。"""
    if not dt:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, get_active_zoneinfo())
    # 仅此文件内允许调用 localtime
    return timezone.localtime(dt, get_active_zoneinfo())


def to_local(dt):
    """任意时间 → 系统本地 aware（展示/比较用）。"""
    return ensure_local_aware(dt)


as_local = to_local


def as_storage_datetime(dt):
    """
    写入数据库 / 与库内时间比较时用的形态。
    USE_TZ=False：系统本地墙钟（无时区）；USE_TZ=True：系统时区 aware。
    """
    if not dt:
        return None
    if settings.USE_TZ:
        return ensure_local_aware(dt)
    if timezone.is_naive(dt):
        return dt
    return timezone.make_naive(ensure_local_aware(dt), get_active_zoneinfo())


def format_local_time(dt, time_fmt='%H:%M', show_date_when_not_today=True):
    """
    格式化为系统本地时间字符串。
    默认只显示「时:分」；若时间不是今天，则带上「月-日」避免跨天误解。
    """
    local_dt = to_local(dt)
    if not local_dt:
        return ''
    if show_date_when_not_today:
        now_local = ensure_local_aware(now_local_wall())
        if local_dt.date() != now_local.date():
            return local_dt.strftime(f'%m-%d {time_fmt}')
    return local_dt.strftime(time_fmt)


def format_local(dt, fmt='%Y-%m-%d %H:%M') -> str:
    """统一 strftime 出口；空时间返回空串。"""
    local_dt = to_local(dt)
    if not local_dt:
        return ''
    return local_dt.strftime(fmt)


def format_local_iso(dt=None) -> str:
    """写出给人看/写进记录文件的 ISO（带系统时区偏移）。"""
    moment = dt if dt is not None else now_local_wall()
    aware = ensure_local_aware(moment)
    return aware.isoformat() if aware else ''


def now_local_wall():
    """
    当前系统本地墙钟（业务取「现在」的唯一推荐出口）。
    USE_TZ=False 时为 naive；USE_TZ=True 时为 aware（本地时区）。
    """
    now = timezone.now()
    if timezone.is_naive(now):
        return now
    return timezone.localtime(now, get_active_zoneinfo())


def local_day_start(moment=None):
    """某日（默认今天）本地 0 点，形态与 now_local_wall 一致。"""
    if moment is not None:
        base = as_storage_datetime(to_local(moment))
    else:
        base = now_local_wall()
    if base is None:
        base = now_local_wall()
    # to_local 可能带回 aware；存库形态再压一次
    base = as_storage_datetime(base) or base
    return base.replace(hour=0, minute=0, second=0, microsecond=0)


def local_today(moment=None):
    """系统本地「今天」的日期；禁止再用 timezone.localdate（USE_TZ=False 会崩）。"""
    return local_day_start(moment).date()


def local_day_bounds_for_query(moment=None):
    """当天 0 点～次日 0 点，适合直接塞进 ORM 查询。"""
    start = local_day_start(moment)
    end = start + timedelta(days=1)
    return start, end
