# 全站模板：店铺工作台导航与独立登录身份、会话守护配置


def nav_shop_work(request):
    """工作台站点标记、店码、工作台登录用户（与生态 user 分开）"""
    from django.urls import reverse

    from .session_guard import HEARTBEAT_TIMEOUT_SECONDS, IDLE_TIMEOUT_SECONDS
    from .shop_work_auth import get_shop_work_user, path_is_shop_work
    from .staff_account_helpers import shop_code_from_request

    path = request.path or ''
    on_shop = path_is_shop_work(path)
    code = shop_code_from_request(request) if on_shop else ''
    work_user = getattr(request, 'shop_work_user', None)
    if work_user is None and on_shop:
        work_user = get_shop_work_user(request)

    logout_url = ''
    if on_shop and code:
        logout_url = reverse('shop_work_logout', kwargs={'shop_code': code})

    has_eco = bool(
        getattr(request.user, 'is_authenticated', False)
        and getattr(request.user, 'role', '') in ('buyer', 'seller')
    )
    has_work = work_user is not None
    session_guard_enabled = has_eco or has_work
    if has_work and not has_eco:
        session_channel = 'work'
    elif has_eco and not has_work:
        session_channel = 'eco'
    else:
        session_channel = 'all'

    return {
        'nav_shop_work_code': code,
        'on_shop_work_site': on_shop,
        'shop_work_user': work_user,
        'shop_work_logout_url': logout_url,
        'session_guard_enabled': session_guard_enabled,
        'session_guard_channel': session_channel,
        'session_heartbeat_seconds': max(30, HEARTBEAT_TIMEOUT_SECONDS // 5),
        'session_idle_seconds': IDLE_TIMEOUT_SECONDS,
        'session_heartbeat_url': reverse('session_heartbeat'),
        'session_beacon_url': reverse('session_beacon_logout'),
    }


def experience_site(request):
    """全站可拿到体验机提示文案（注册页等已单独注入，这里供通用模板）"""
    from .experience_helpers import experience_hint_context, experience_site_enabled

    if not experience_site_enabled():
        return {'experience_site': False, 'experience_hint': ''}
    return experience_hint_context()


def site_compliance(request):
    """向全站公共页脚提供备案信息；迁移尚未执行时保持页面可打开。"""
    from django.db.utils import OperationalError, ProgrammingError

    from .models import SiteComplianceSettings

    try:
        compliance = SiteComplianceSettings.objects.first()
    except (OperationalError, ProgrammingError):
        compliance = None
    return {'site_compliance': compliance}

