# 登录会话守护：心跳、无操作超时、关页尽量退出

from django.contrib.auth import logout as ecosystem_logout
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

# 约 5 分钟无报平安 → 会话失效（与 settings.SESSION_COOKIE_AGE 对齐）
HEARTBEAT_TIMEOUT_SECONDS = 5 * 60
# 超过 15 分钟无操作 → 退出
IDLE_TIMEOUT_SECONDS = 15 * 60

SESSION_LAST_ACTIVITY = 'yc_last_activity_ts'
SESSION_LAST_HEARTBEAT = 'yc_last_heartbeat_ts'


def _now_ts() -> float:
    return timezone.now().timestamp()


def touch_user_activity(request) -> None:
    """记录用户真实操作时间（心跳请求不要调用）"""
    request.session[SESSION_LAST_ACTIVITY] = _now_ts()
    request.session.modified = True


def touch_heartbeat(request) -> None:
    """心跳：延长会话寿命，但不算「有操作」"""
    request.session[SESSION_LAST_HEARTBEAT] = _now_ts()
    # 访问 session 即刷新过期时间（配合 SESSION_COOKIE_AGE）
    request.session.modified = True


def idle_expired(request) -> bool:
    """是否超过无操作时限"""
    raw = request.session.get(SESSION_LAST_ACTIVITY)
    if raw is None:
        return False
    try:
        last = float(raw)
    except (TypeError, ValueError):
        return False
    return (_now_ts() - last) > IDLE_TIMEOUT_SECONDS


def force_logout_all_channels(request) -> None:
    """同时清掉生态登录与工作台登录（超时 / 关页兜底）"""
    logout_eco_channel(request)
    logout_work_channel(request)


def logout_work_channel(request) -> None:
    """仅清工作台登录"""
    from .shop_work_auth import clear_shop_work_session, get_shop_work_user
    from .staff_account_helpers import deactivate_staff_on_logout

    work_user = get_shop_work_user(request)
    if work_user and work_user.role in ('waiter', 'kitchen', 'rider', 'manager'):
        deactivate_staff_on_logout(work_user)
    clear_shop_work_session(request)


def logout_eco_channel(request) -> None:
    """仅清野草生态登录（保留工作台会话）"""
    from .shop_work_auth import restore_shop_work_session, snapshot_shop_work_session

    if not getattr(request.user, 'is_authenticated', False):
        return
    snap = snapshot_shop_work_session(request)
    ecosystem_logout(request)
    restore_shop_work_session(request, snap)


def logout_by_channel(request, channel: str) -> None:
    """按页面通道只退一侧，避免店主与员工互相踢下线"""
    ch = (channel or '').strip()
    if ch == 'work':
        logout_work_channel(request)
    elif ch == 'eco':
        logout_eco_channel(request)
    else:
        force_logout_all_channels(request)


@require_POST
def session_heartbeat(request):
    """页面报平安：延长会话；可选附带「有操作」标记"""
    from .shop_work_auth import get_shop_work_user

    channel = (request.POST.get('channel') or 'all').strip()
    has_eco = getattr(request.user, 'is_authenticated', False)
    has_work = get_shop_work_user(request) is not None
    if not has_eco and not has_work:
        return JsonResponse({'ok': False, 'reason': 'not_logged_in'}, status=401)

    if idle_expired(request):
        logout_by_channel(request, channel)
        return JsonResponse({'ok': False, 'reason': 'idle_timeout', 'logout': True})

    touch_heartbeat(request)
    if request.POST.get('activity') == '1':
        touch_user_activity(request)
    elif SESSION_LAST_ACTIVITY not in request.session:
        # 首次心跳也记一次，避免立刻被判空闲
        touch_user_activity(request)

    from .experience_helpers import request_presence_user, touch_online_user

    presence = request_presence_user(request)
    if presence is None:
        presence = get_shop_work_user(request)
    touch_online_user(presence)

    return JsonResponse({
        'ok': True,
        'heartbeat_seconds': HEARTBEAT_TIMEOUT_SECONDS,
        'idle_seconds': IDLE_TIMEOUT_SECONDS,
    })


@csrf_exempt
@require_POST
def session_beacon_logout(request):
    """
    关页尽量退出：供 navigator.sendBeacon 调用。
    仍校验 CSRF（从 form 字段或头读取）；失败则忽略，靠 5 分钟无心跳兜底。
    """
    from django.middleware.csrf import CsrfViewMiddleware

    # 手动做一次 CSRF 检查（sendBeacon 常带 form 字段）
    class _Probe(CsrfViewMiddleware):
        def _reject(self, request, reason):
            return reason

    probe = _Probe(lambda r: None)
    bad = probe.process_view(request, None, (), {})
    if bad:
        return JsonResponse({'ok': False, 'reason': 'csrf'}, status=403)

    channel = (request.POST.get('channel') or 'all').strip()
    from .shop_work_auth import get_shop_work_user

    if channel == 'work':
        logout_work_channel(request)
    elif channel == 'eco':
        logout_eco_channel(request)
    else:
        force_logout_all_channels(request)

    return JsonResponse({'ok': True})
