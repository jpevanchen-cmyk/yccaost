# 野草本地营业内测版 V1.0：模式判断与隐藏清单（§5.16.5 / §5.16.5.1）
# 默认非 V1；仅环境变量显式开启或库内安装模式为 v1_local 时生效。

from __future__ import annotations

from django.conf import settings

# 安装模式：标准（完整野草） / V1 本地营业内测
INSTALL_MODE_STANDARD = 'standard'
INSTALL_MODE_V1_LOCAL = 'v1_local'

INSTALL_MODE_CHOICES = (
    (INSTALL_MODE_STANDARD, '标准（完整功能）'),
    (INSTALL_MODE_V1_LOCAL, '本地营业内测版 V1.0'),
)

# V1 下卖家后台应隐藏的分区（Tab 不显示、直接访问也进不去）
V1_HIDDEN_SELLER_SECTIONS = frozenset({'homepage'})

# V1 下禁止访问的网址前缀（静态资源、支付通知等在中件件里另放行）
V1_BLOCKED_PATH_PREFIXES = (
    '/register',
    '/shop-register',
    '/guestbook',
    '/public-wall',
    '/experience',
    '/directory',
    '/showcase',
    '/rider-home',
    '/kitchen-home',
    '/waiter-home',
    '/knight-hall',
    '/owner-hub',
    '/server-settings/home',
    '/server-settings/guestbook',
    '/server-settings/public-wall',
    '/owner/server-home',
)

# 中件件始终放行的前缀（与业务无关或须保留）
V1_MIDDLEWARE_SKIP_PREFIXES = (
    '/static/',
    '/media/',
    '/accounts/session/',
    '/pay/wechat/notify/',
)

_v1_install_mode_cache: str | None = None


def v1_local_mode_from_settings() -> bool:
    """环境变量 YECAO_V1_LOCAL_MODE=1 时开启（专项验收用）。"""
    return bool(getattr(settings, 'YECAO_V1_LOCAL_MODE', False))


def clear_v1_install_mode_cache() -> None:
    """写入安装模式后清缓存。"""
    global _v1_install_mode_cache
    _v1_install_mode_cache = None


def get_db_install_mode() -> str:
    """读库内安装模式；缺省或异常时为标准模式。"""
    global _v1_install_mode_cache
    if _v1_install_mode_cache is not None:
        return _v1_install_mode_cache
    mode = INSTALL_MODE_STANDARD
    try:
        from django.db.utils import OperationalError, ProgrammingError

        from .models import ServerSiteSettings

        row = ServerSiteSettings.objects.filter(singleton_id=1).only('install_mode').first()
        if row and (row.install_mode or '').strip():
            mode = row.install_mode.strip()
    except (OperationalError, ProgrammingError):
        mode = INSTALL_MODE_STANDARD
    except Exception:
        mode = INSTALL_MODE_STANDARD
    if mode not in (INSTALL_MODE_STANDARD, INSTALL_MODE_V1_LOCAL):
        mode = INSTALL_MODE_STANDARD
    _v1_install_mode_cache = mode
    return mode


def v1_local_mode_enabled() -> bool:
    """
    是否处于 V1 本地营业内测模式。
    环境变量或库字段任一开启即生效；开发机默认两者皆关。
    """
    if v1_local_mode_from_settings():
        return True
    return get_db_install_mode() == INSTALL_MODE_V1_LOCAL


def should_serve_uploaded_media() -> bool:
    """
    是否由本程序提供上传文件（/media/）。
    调试开启，或 V1 本地营业（无 Nginx）时为真；
    云上正式部署关调试且非 V1 时交给 Nginx，避免与网关抢同一路径。
    """
    if settings.DEBUG:
        return True
    return v1_local_mode_enabled()


def uploaded_media_urlpatterns() -> list:
    """
    需要本程序送上传文件时，返回 /media/ 的网址登记列表。
    注意：django.conf.urls.static.static() 在 DEBUG=False 时故意返回空列表，
    关调试的 V1 包不能调用它指望生效，必须在此显式挂上读盘送文件。
    """
    if not should_serve_uploaded_media():
        return []
    import re

    from django.urls import re_path
    from django.views.static import serve

    prefix = (getattr(settings, 'MEDIA_URL', None) or '').lstrip('/')
    root = getattr(settings, 'MEDIA_ROOT', None)
    if not prefix or not root:
        return []
    return [
        re_path(
            r'^%s(?P<path>.*)$' % re.escape(prefix),
            serve,
            {'document_root': root},
        ),
    ]


def set_db_install_mode(mode: str) -> None:
    """写入库内安装模式（首次向导等后续步骤调用）。"""
    from .owner_helpers import get_site_settings

    normalized = (mode or '').strip() or INSTALL_MODE_STANDARD
    if normalized not in (INSTALL_MODE_STANDARD, INSTALL_MODE_V1_LOCAL):
        normalized = INSTALL_MODE_STANDARD
    site = get_site_settings()
    if site.install_mode != normalized:
        site.install_mode = normalized
        site.save(update_fields=['install_mode', 'updated_at'])
    clear_v1_install_mode_cache()


def v1_local_block_message() -> str:
    """V1 模式下访问已关闭功能时的白话提示。"""
    return '本地营业内测版未开放此功能；请使用店内营业入口或联系管理员。'


def seller_section_hidden_in_v1(section: str) -> bool:
    """V1 模式下该卖家后台分区是否应隐藏。"""
    if not v1_local_mode_enabled():
        return False
    return (section or '').strip() in V1_HIDDEN_SELLER_SECTIONS


def path_is_v1_blocked(path: str) -> bool:
    """当前路径在 V1 模式下是否应拦截。"""
    path = (path or '/').split('?', 1)[0]
    if not path.startswith('/'):
        path = '/' + path
    # 服务器主页根地址
    if path in ('', '/'):
        return True
    # 店铺门面页 /s/店码/home/
    if path.startswith('/s/') and '/home/' in path:
        return True
    return any(path.startswith(prefix) for prefix in V1_BLOCKED_PATH_PREFIXES)


def path_skips_v1_middleware(path: str) -> bool:
    """中件件直接放行、不做 V1 拦截判断的路径。"""
    path = path or ''
    return any(path.startswith(prefix) for prefix in V1_MIDDLEWARE_SKIP_PREFIXES)
