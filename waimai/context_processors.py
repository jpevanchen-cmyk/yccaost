# 全站模板：店铺工作台导航与独立登录身份、会话守护配置


def nav_shop_work(request):
    """工作台站点标记、店码、工作台登录用户（与生态 user 分开）"""
    from django.urls import reverse

    from .session_guard import (
        IDLE_TIMEOUT_SECONDS,
        SESSION_HEARTBEAT_INTERVAL_SECONDS,
    )
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
    # 关页 / 空闲退出按「当前页面」分通道，避免店主与员工互相踢下线
    session_channel = _session_guard_channel_for_path(path, has_eco=has_eco, has_work=has_work)

    return {
        'nav_shop_work_code': code,
        'on_shop_work_site': on_shop,
        'shop_work_user': work_user,
        'shop_work_logout_url': logout_url,
        'session_guard_enabled': session_guard_enabled,
        'session_guard_channel': session_channel,
        'session_heartbeat_seconds': SESSION_HEARTBEAT_INTERVAL_SECONDS,
        'session_idle_seconds': IDLE_TIMEOUT_SECONDS,
        'session_heartbeat_url': reverse('session_heartbeat'),
        'session_beacon_url': reverse('session_beacon_logout'),
    }


def _session_guard_channel_for_path(path: str, *, has_eco: bool, has_work: bool) -> str:
    """根据当前网址判断关页时只退哪一侧登录"""
    from .shop_work_auth import path_is_shop_work

    path = path or ''
    if path_is_shop_work(path):
        return 'work'
    if path.startswith('/waiter-home/'):
        return 'work'
    if path.startswith('/seller-panel') or path.startswith('/accounts/'):
        return 'eco'
    if path.startswith('/order-history') or path.startswith('/order/') or path.startswith('/pay/'):
        return 'eco'
    if path.startswith('/directory') or path.startswith('/shop') or path.startswith('/place-order'):
        return 'eco'
    if has_work and not has_eco:
        return 'work'
    if has_eco and not has_work:
        return 'eco'
    return 'eco' if has_eco else 'work'


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


def site_branding(request):
    """全站顶部名称、导航名、服务器设置入口"""
    from django.db.utils import OperationalError, ProgrammingError

    from .owner_helpers import get_site_settings, user_is_server_manager

    site_name = '野草系统'
    nav_label = '店铺名录'
    show_powered_by = True
    brand_image_url = ''
    try:
        site = get_site_settings()
        site_name = site.site_name or site_name
        nav_label = site.nav_brand_label or nav_label
        show_powered_by = bool(site.show_powered_by)
        brand_image_url = site.brand_image_url or ''
    except (OperationalError, ProgrammingError):
        pass

    user = getattr(request, 'user', None)
    show_server_settings = False
    try:
        show_server_settings = bool(
            user
            and getattr(user, 'is_authenticated', False)
            and user_is_server_manager(user)
        )
    except (OperationalError, ProgrammingError):
        show_server_settings = False

    return {
        'site_brand_name': site_name,
        'site_nav_label': nav_label,
        'site_show_powered_by': show_powered_by,
        'site_brand_image_url': brand_image_url,
        'show_owner_console_link': show_server_settings,  # 模板兼容旧变量名
        'show_server_settings_link': show_server_settings,
    }

