# 店内可访问根地址：唯一真源为堂食 table_lan_base_url（§5.16.3.1）
# 本机打开后台走 127，与这份店内地址脱钩。禁止为展示再存第二份。

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, JsonResponse


def listen_port() -> int:
    """网页服务端口：跟向导/站点已存端口；没有则 8000。"""
    from .owner_helpers import get_site_settings

    port = get_site_settings().v1_listen_port
    try:
        return int(port or 8000)
    except (TypeError, ValueError):
        return 8000


def local_open_backend_url(port: int | None = None) -> str:
    """本机打开老板后台的默认地址（回路，不读店内地址）。"""
    p = port if port is not None else listen_port()
    return f'http://127.0.0.1:{int(p)}/accounts/login/'


def primary_seller_id() -> str:
    """本机主店账号：优先服务器管理者，否则第一家店。"""
    from django.contrib.auth import get_user_model

    from .models import ShopProfile

    User = get_user_model()
    owner = User.objects.filter(role='seller', is_server_owner=True).order_by('id').first()
    if owner:
        return owner.username
    shop = ShopProfile.objects.order_by('seller_id').first()
    return (shop.seller_id if shop else '') or ''


def get_shop_lan_base_url(seller_id: str = '') -> str:
    """
    店内可扫根地址的唯一真源：堂食 table_lan_base_url。
    仅当该格为空时，才读旧的站点 v1_lan 作兼容（只读、不写回）。
    """
    from .operating_helpers import get_operating_settings, http_base_is_loopback
    from .owner_helpers import get_site_settings

    sid = (seller_id or '').strip() or primary_seller_id()
    if sid:
        lan = (
            getattr(get_operating_settings(sid), 'table_lan_base_url', '') or ''
        ).strip().rstrip('/')
        if lan and not http_base_is_loopback(lan):
            return lan

    v1 = (getattr(get_site_settings(), 'v1_lan_base_url', '') or '').strip().rstrip('/')
    if v1 and not http_base_is_loopback(v1):
        return v1
    return ''


def detect_current_lan_base_url(port: int | None = None) -> str:
    """探测当前店内网址；失败返回空串（禁止用 127 顶上）。"""
    from .v1_setup_helpers import default_lan_base_url

    return default_lan_base_url(port if port is not None else listen_port())


def _norm_lan(url: str) -> str:
    return (url or '').strip().rstrip('/').lower()


def lan_urls_match(saved: str, detected: str) -> bool:
    a, b = _norm_lan(saved), _norm_lan(detected)
    if not a or not b:
        return False
    return a == b


def lan_sync_ui_allowed(request: HttpRequest | None = None) -> bool:
    """
    是否展示检测/一键：V1 安装包，或开发机（开着调试）。
    云上正式站关调试且非 V1，避免把云内网号一键写进桌码。
    """
    from .v1_local_helpers import v1_local_mode_enabled

    if v1_local_mode_enabled():
        return True
    return bool(getattr(settings, 'DEBUG', False))


def compare_saved_and_detected(seller_id: str = '') -> dict:
    """已保存 / 当前探测 / 是否一致。不写库。"""
    sid = (seller_id or '').strip() or primary_seller_id()
    port = listen_port()
    saved = get_shop_lan_base_url(sid)
    detected = detect_current_lan_base_url(port)
    match = lan_urls_match(saved, detected)
    detect_failed = not bool(detected)
    if detect_failed:
        message = (
            '测不到当前店内号。本机仍可用「本机打开后台」进入；'
            '请手工填写四段数字。不要用 127.0.0.1 去顶店内地址。'
        )
    elif match:
        message = '已保存的店内地址与当前探测一致。'
    elif not saved:
        message = '还没有保存店内地址。确认探测结果无误后，可一键写入。'
    else:
        message = (
            '已保存的号和当前探测不一致。换网后手机扫旧码可能打不开。'
            '确认后可一键更新；已印桌贴若含旧号须重打。'
        )
    return {
        'ok': True,
        'saved_lan': saved,
        'detected_lan': detected,
        'match': match,
        'detect_failed': detect_failed,
        'listen_port': port,
        'open_url': local_open_backend_url(port),
        'seller_id': sid,
        'message': message,
        'sync_ui': True,
    }


def apply_shop_lan_base_url(seller_id: str, url: str) -> tuple[bool, str]:
    """
    把店内根地址写入唯一真源（堂食 table_lan）并放行。
    禁止 127。同一地址再写一次视为成功（幂等）。不写站点 v1_lan。
    """
    from .operating_helpers import get_operating_settings, http_base_is_loopback
    from .v1_allowed_hosts_helpers import apply_lan_url_to_allowed_hosts
    from .v1_setup_helpers import lan_base_url_rejection_message

    text = (url or '').strip().rstrip('/')
    if not text:
        return False, '没有可保存的店内地址。请先检测成功，或手工填写四段数字。'
    reject = lan_base_url_rejection_message(text)
    if reject:
        return False, reject
    if http_base_is_loopback(text):
        return False, '不能把 127.0.0.1 当作店内地址。'

    sid = (seller_id or '').strip() or primary_seller_id()
    if not sid:
        return False, '还没有店铺，无法保存店内地址。'

    op = get_operating_settings(sid)
    current = (op.table_lan_base_url or '').strip().rstrip('/')
    if _norm_lan(current) == _norm_lan(text):
        apply_lan_url_to_allowed_hosts(text)
        return True, '店内地址未变化。已核对放行名单。'

    op.table_lan_base_url = text
    op.save(update_fields=['table_lan_base_url'])
    apply_lan_url_to_allowed_hosts(text)
    return True, (
        '已更新店内地址。若桌上贴的码还是旧号，请重新导出打印。'
        '正式店建议在路由器做地址保留，减少号码乱跳。'
    )


def apply_detected_lan_base_url(seller_id: str = '') -> tuple[bool, str, dict]:
    """探测当前号并写入真源。探测失败不改已存地址。"""
    sid = (seller_id or '').strip() or primary_seller_id()
    snapshot = compare_saved_and_detected(sid)
    if snapshot['detect_failed']:
        snapshot['ok'] = False
        return False, snapshot['message'], snapshot
    ok, msg = apply_shop_lan_base_url(sid, snapshot['detected_lan'])
    after = compare_saved_and_detected(sid)
    after['ok'] = ok
    after['message'] = msg
    return ok, msg, after


def wants_json(request: HttpRequest) -> bool:
    if (request.headers.get('X-Requested-With') or '') == 'XMLHttpRequest':
        return True
    accept = (request.headers.get('Accept') or '').lower()
    return 'application/json' in accept


def json_lan_payload(payload: dict, *, status: int = 200) -> JsonResponse:
    return JsonResponse(payload, status=status, json_dumps_params={'ensure_ascii': False})
