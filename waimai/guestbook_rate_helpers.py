# 留言身份键与按人限流

from __future__ import annotations

import uuid
from datetime import timedelta

from .time_helpers import now_local_wall

GUESTBOOK_ACTOR_COOKIE = 'yc_gb_actor'
SESSION_ACTOR_KEY = 'yc_gb_actor_key'


def resolve_guestbook_actor(request) -> tuple[str, str | None]:
    """
    确定留言限流用的身份键。
    已登录：按账号；未登录：按浏览器访客编号。
    返回 (actor_key, new_cookie_value或None)。
    """
    user = getattr(request, 'user', None)
    if user and getattr(user, 'is_authenticated', False):
        username = (getattr(user, 'username', '') or '').strip()
        if username:
            return f'user:{username}', None

    raw = (request.COOKIES.get(GUESTBOOK_ACTOR_COOKIE) or '').strip()
    if raw:
        if not request.session.get(SESSION_ACTOR_KEY):
            request.session[SESSION_ACTOR_KEY] = raw
            request.session.modified = True
        return f'anon:{raw}', None

    session_raw = (request.session.get(SESSION_ACTOR_KEY) or '').strip()
    if session_raw:
        return f'anon:{session_raw}', session_raw

    new_key = uuid.uuid4().hex
    request.session[SESSION_ACTOR_KEY] = new_key
    request.session.modified = True
    return f'anon:{new_key}', new_key


def _guestbook_hourly_max() -> int:
    from django.conf import settings

    return int(getattr(settings, 'YECAO_GUESTBOOK_ACTOR_HOURLY_MAX', 3))


def _guestbook_daily_max() -> int:
    from django.conf import settings

    return int(getattr(settings, 'YECAO_GUESTBOOK_ACTOR_DAILY_MAX', 15))


def _local_day_start():
    """系统本地当天 0 点（查询用；USE_TZ=False 时必须是 naive）"""
    from .time_helpers import local_day_bounds_for_query

    start, _end = local_day_bounds_for_query()
    return start


def check_guestbook_rate_limit(actor_key: str) -> tuple[bool, str]:
    """按身份检查留言频率；通过返回 (True, '')"""
    from .guestbook_models import GuestbookThread

    key = (actor_key or '').strip()
    if not key:
        return True, ''

    hourly_max = _guestbook_hourly_max()
    daily_max = _guestbook_daily_max()
    hour_ago = now_local_wall() - timedelta(hours=1)
    day_start = _local_day_start()

    hourly_count = GuestbookThread.objects.filter(
        guest_actor_key=key, created_at__gte=hour_ago,
    ).count()
    if hourly_count >= hourly_max:
        return False, f'您本小时留言已达上限（{hourly_max} 条），请稍后再试'

    daily_count = GuestbookThread.objects.filter(
        guest_actor_key=key, created_at__gte=day_start,
    ).count()
    if daily_count >= daily_max:
        return False, f'您今日留言已达上限（{daily_max} 条），请明天再试'

    return True, ''
