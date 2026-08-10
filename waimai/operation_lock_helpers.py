# V1 操作锁：仅店铺管理后台（§5.16.11；服务器设置不锁）

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import quote

from django.urls import reverse
from django.utils import timezone
from .time_helpers import now_local_wall

SESSION_OP_LOCK_ACTIVITY = 'yc_op_lock_activity_ts'
DEFAULT_OP_LOCK_IDLE_SECONDS = 300
_PBKDF2_ITERS = 200_000

PROTECTED_PREFIXES = (
    '/seller-panel/',
)

EXEMPT_PREFIXES = (
    '/operation-lock/',
    '/accounts/',
    '/static/',
    '/media/',
)


def _now_ts() -> float:
    return now_local_wall().timestamp()


def path_skips_operation_lock(path: str) -> bool:
    path = (path or '').split('?', 1)[0]
    return any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES)


def path_in_operation_lock_scope(path: str) -> bool:
    path = (path or '').split('?', 1)[0]
    return any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def operation_lock_configured(site) -> bool:
    return bool(
        site.operation_lock_enabled
        and (site.operation_lock_pin_hash or '').strip()
        and (site.operation_lock_pin_salt or '').strip()
    )


def site_operation_lock_enabled() -> bool:
    from .owner_helpers import get_site_settings

    site = get_site_settings()
    return operation_lock_configured(site)


def _hash_pin(plain: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac(
        'sha256',
        plain.encode('utf-8'),
        salt,
        _PBKDF2_ITERS,
    )
    return base64.b64encode(digest).decode('ascii')


def set_operation_lock_pin(site, plain: str) -> None:
    salt = secrets.token_bytes(16)
    site.operation_lock_pin_salt = base64.b64encode(salt).decode('ascii')
    site.operation_lock_pin_hash = _hash_pin(plain, salt)


def clear_operation_lock_pin(site) -> None:
    site.operation_lock_pin_salt = ''
    site.operation_lock_pin_hash = ''
    site.operation_lock_enabled = False


def verify_operation_lock_pin(site, plain: str) -> bool:
    if not operation_lock_configured(site):
        return False
    try:
        salt = base64.b64decode(site.operation_lock_pin_salt)
        expected = site.operation_lock_pin_hash
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(_hash_pin(plain or '', salt), expected)


def request_in_operation_lock_scope(request) -> bool:
    return path_in_operation_lock_scope(request.path or '')


def request_user_subject_to_operation_lock(request) -> bool:
    user = getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    path = request.path or ''
    if path.startswith('/seller-panel/'):
        return getattr(user, 'role', '') == 'seller'
    return False


def operation_lock_idle_seconds(site) -> int:
    raw = int(getattr(site, 'operation_lock_idle_seconds', None) or DEFAULT_OP_LOCK_IDLE_SECONDS)
    return max(60, min(raw, 3600))


def touch_operation_lock_activity(request) -> None:
    request.session[SESSION_OP_LOCK_ACTIVITY] = _now_ts()
    request.session.modified = True


def engage_operation_lock(request) -> None:
    request.session.pop(SESSION_OP_LOCK_ACTIVITY, None)
    request.session.modified = True


def operation_lock_is_engaged(request) -> bool:
    """当前请求是否应被操作锁拦住。"""
    from .owner_helpers import get_site_settings

    if not request_in_operation_lock_scope(request):
        return False
    if not request_user_subject_to_operation_lock(request):
        return False
    site = get_site_settings()
    if not operation_lock_configured(site):
        return False
    last = request.session.get(SESSION_OP_LOCK_ACTIVITY)
    if last is None:
        return True
    try:
        last_ts = float(last)
    except (TypeError, ValueError):
        return True
    idle = operation_lock_idle_seconds(site)
    return (_now_ts() - last_ts) > idle


def unlock_operation_lock(request, pin: str) -> tuple[bool, str]:
    from .owner_helpers import get_site_settings

    site = get_site_settings()
    if not operation_lock_configured(site):
        return True, '操作锁未启用'
    if not verify_operation_lock_pin(site, pin):
        return False, '操作 PIN 不正确'
    touch_operation_lock_activity(request)
    return True, '已解锁'


def manual_operation_lock(request) -> None:
    engage_operation_lock(request)


def operation_lock_unlock_url(next_path: str = '') -> str:
    base = reverse('operation_lock_unlock')
    nxt = (next_path or '').strip()
    if nxt:
        return f'{base}?next={quote(nxt, safe="/:?=&")}'
    return base
