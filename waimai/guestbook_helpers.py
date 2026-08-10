# 留言板辅助：提交、回复、密码、站点链接

from __future__ import annotations

from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone
from .time_helpers import now_local_wall

MAX_BODY = 1000
MAX_NAME = 80
MAX_PASSWORD = 8
SESSION_UNLOCK_PREFIX = 'gb_unlock:'
# 短时间去重：同一人、同内容、同邮箱在窗口内只保留一条
DEDUPE_WINDOW_SECONDS = 120


def get_guestbook_settings():
    from .guestbook_models import GuestbookSettings

    obj, _ = GuestbookSettings.objects.get_or_create(singleton_id=1)
    return obj


def guestbook_public_site_url() -> str:
    """邮件与说明里用的主页地址"""
    from django.conf import settings

    url = (getattr(settings, 'YECAO_PUBLIC_SITE_URL', '') or '').strip().rstrip('/')
    if url:
        return url
    return 'https://yichbo.com'


def guestbook_search_hint_text() -> str:
    """邮件 footer 共用：说明如何用编号（不含重复的主页网址）"""
    return '在「联系我们 / 留言板」处输入您的留言编号，即可查看回复并继续沟通。'


def guest_display_label(request, name: str) -> str:
    name = (name or '').strip()
    if name:
        return name[:MAX_NAME]
    user = getattr(request, 'user', None)
    if user and getattr(user, 'is_authenticated', False):
        return user.username[:MAX_NAME]
    return '游客'


def hash_guest_password(raw: str) -> str:
    text = (raw or '').strip()
    if not text:
        return ''
    return make_password(text[:MAX_PASSWORD])


def verify_guest_password(thread, raw: str) -> bool:
    stored = (thread.guest_password_hash or '').strip()
    if not stored:
        return True
    return check_password((raw or '').strip()[:MAX_PASSWORD], stored)


def is_thread_unlocked(request, thread) -> bool:
    if not thread.has_view_password:
        return True
    key = f'{SESSION_UNLOCK_PREFIX}{thread.thread_id}'
    return bool(request.session.get(key))


def mark_thread_unlocked(request, thread) -> None:
    request.session[f'{SESSION_UNLOCK_PREFIX}{thread.thread_id}'] = True
    request.session.modified = True


def _client_ip(request) -> str | None:
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    if forwarded:
        return forwarded[:45]
    raw = request.META.get('REMOTE_ADDR')
    return raw[:45] if raw else None


def _find_recent_duplicate_thread(actor_key: str, body: str, email: str):
    """2 分钟内同身份、同内容、同邮箱 → 视为重复提交，返回已有主题"""
    from datetime import timedelta

    from .guestbook_models import GuestbookMessage, GuestbookThread

    key = (actor_key or '').strip()
    text = (body or '').strip()
    if not key or not text:
        return None

    email_norm = (email or '').strip().lower()
    since = now_local_wall() - timedelta(seconds=DEDUPE_WINDOW_SECONDS)
    candidates = GuestbookThread.objects.filter(
        guest_actor_key=key,
        created_at__gte=since,
    ).order_by('-created_at')[:10]

    for thread in candidates:
        if (thread.guest_email or '').strip().lower() != email_norm:
            continue
        first_msg = (
            GuestbookMessage.objects.filter(thread=thread, author_side='guest')
            .order_by('created_at')
            .first()
        )
        if first_msg and first_msg.body.strip() == text:
            return thread
    return None


def _apply_receipt_email_status(thread, email_result: str) -> str:
    """根据发信结果写库，并返回提交结果类型"""
    from .guestbook_ui_helpers import (
        RESULT_EMAIL_FAILED,
        RESULT_OK,
        RESULT_OK_NO_EMAIL,
        RESULT_RATE_LIMITED,
    )

    email = (thread.guest_email or '').strip()
    if not email:
        return RESULT_OK_NO_EMAIL
    if email_result == 'sent':
        thread.receipt_email_failed = False
        thread.receipt_email_rate_limited = False
        thread.save(update_fields=['receipt_email_failed', 'receipt_email_rate_limited'])
        return RESULT_OK
    if email_result == 'rate_limited':
        thread.receipt_email_failed = False
        thread.receipt_email_rate_limited = True
        thread.save(update_fields=['receipt_email_failed', 'receipt_email_rate_limited'])
        return RESULT_RATE_LIMITED
    if email_result == 'failed':
        thread.receipt_email_failed = True
        thread.receipt_email_rate_limited = False
        thread.save(update_fields=['receipt_email_failed', 'receipt_email_rate_limited'])
        return RESULT_EMAIL_FAILED
    return RESULT_OK_NO_EMAIL


def _build_submit_payload(
    thread,
    *,
    duplicate: bool = False,
    has_password: bool = False,
    result_type: str | None = None,
) -> dict:
    from .guestbook_ui_helpers import (
        RESULT_DUPLICATE,
        guestbook_submit_result_ui,
        thread_email_result_type,
    )

    if duplicate:
        rt = RESULT_DUPLICATE
    else:
        rt = result_type or thread_email_result_type(thread)
    ui = guestbook_submit_result_ui(rt, duplicate=duplicate)
    return {
        'public_code': thread.public_code,
        'result_type': rt,
        'result_title': ui['title'],
        'result_message': ui['message'],
        'result_level': ui['level'],
        'duplicate': duplicate,
        'has_password': has_password,
        # 兼容旧字段
        'email_sent': rt == 'ok',
        'email_failed': rt == 'email_failed',
        'email_rate_limited': rt == 'rate_limited',
        'message': ui['title'],
    }


def _payload_for_existing_thread(thread, *, duplicate: bool = False) -> dict:
    return _build_submit_payload(
        thread,
        duplicate=duplicate,
        has_password=thread.has_view_password,
    )


def can_guest_manage_thread(request, thread) -> bool:
    """访客是否有权改邮箱等（须已解锁且身份匹配）"""
    if not is_thread_unlocked(request, thread):
        return False

    user = getattr(request, 'user', None)
    if user and getattr(user, 'is_authenticated', False):
        snap = (thread.guest_user_id or '').strip()
        if snap and snap == (getattr(user, 'username', '') or '').strip():
            return True

    from .guestbook_rate_helpers import resolve_guestbook_actor

    actor_key, _ = resolve_guestbook_actor(request)
    stored = (thread.guest_actor_key or '').strip()
    if stored and actor_key == stored:
        return True
    if not stored:
        return True
    return False


def update_guestbook_email(request, thread, new_email: str) -> tuple[bool, str]:
    """访客在编号页更新联系邮箱，并尝试重发收条邮件"""
    if not can_guest_manage_thread(request, thread):
        return False, '无权修改此留言的联系邮箱'

    email = (new_email or '').strip()
    if not email:
        return False, '请填写联系邮箱'
    try:
        validate_email(email)
    except ValidationError:
        return False, '邮箱格式不正确'

    from .guestbook_notify import notify_guest_receipt_email

    thread.guest_email = email[:254]
    thread.receipt_email_failed = False
    thread.receipt_email_rate_limited = False
    thread.email_delivery_suspect = False
    thread.save(
        update_fields=[
            'guest_email', 'receipt_email_failed',
            'receipt_email_rate_limited', 'email_delivery_suspect',
        ],
    )

    email_result = notify_guest_receipt_email(thread)
    if email_result == 'sent':
        return True, '邮箱已更新，收条邮件已发送'
    if email_result == 'rate_limited':
        thread.receipt_email_rate_limited = True
        thread.save(update_fields=['receipt_email_rate_limited'])
        from .guestbook_ui_helpers import guestbook_rate_limit_detail

        return True, '邮箱已保存。' + guestbook_rate_limit_detail()
    if email_result == 'failed':
        thread.receipt_email_failed = True
        thread.save(update_fields=['receipt_email_failed'])
        return True, '邮箱已保存，但收条邮件仍未发出，请核对地址是否正确'
    return True, '邮箱已保存'


def post_guestbook_message(
    request,
    *,
    body: str,
    guest_name: str = '',
    guest_email: str = '',
    guest_password: str = '',
) -> tuple[bool, dict]:
    """
    新建留言主题。
    成功返回 (True, payload)；失败返回 (False, {'error': '...'})。
    """
    from .guestbook_code_helpers import generate_public_code
    from .guestbook_models import GuestbookMessage, GuestbookThread
    from .guestbook_notify import notify_guest_receipt_email, notify_manager_new_guestbook
    from .guestbook_rate_helpers import check_guestbook_rate_limit, resolve_guestbook_actor
    from .guestbook_ui_helpers import RESULT_OK_NO_EMAIL

    actor_key, new_cookie = resolve_guestbook_actor(request)
    if new_cookie:
        request._yc_new_guestbook_actor = new_cookie

    ok_limit, limit_msg = check_guestbook_rate_limit(actor_key)
    if not ok_limit:
        return False, {'error': limit_msg}

    text = (body or '').strip()
    if len(text) < 2:
        return False, {'error': '请至少填写两个字'}
    if len(text) > MAX_BODY:
        return False, {'error': f'留言请控制在 {MAX_BODY} 字以内'}

    pwd_raw = (guest_password or '').strip()
    if len(pwd_raw) > MAX_PASSWORD:
        return False, {'error': f'查看密码请不超过 {MAX_PASSWORD} 位'}

    email = (guest_email or '').strip()
    if email:
        try:
            validate_email(email)
        except ValidationError:
            return False, {'error': '邮箱格式不正确'}

    label = guest_display_label(request, guest_name)
    user = getattr(request, 'user', None)
    user_snap = user.username if user and getattr(user, 'is_authenticated', False) else ''

    dup = _find_recent_duplicate_thread(actor_key, text, email)
    if dup:
        return True, _payload_for_existing_thread(dup, duplicate=True)

    public_code = generate_public_code()
    thread = GuestbookThread.objects.create(
        public_code=public_code,
        guest_display_name=label,
        guest_email=email,
        guest_user_id=user_snap,
        guest_actor_key=actor_key,
        guest_password_hash=hash_guest_password(pwd_raw),
        author_ip=_client_ip(request),
    )
    msg = GuestbookMessage.objects.create(
        thread=thread,
        author_side='guest',
        author_label=label,
        body=text,
    )

    notify_manager_new_guestbook(thread, msg)

    result_type = RESULT_OK_NO_EMAIL
    if email:
        email_result = notify_guest_receipt_email(thread)
        result_type = _apply_receipt_email_status(thread, email_result)

    return True, _build_submit_payload(
        thread,
        has_password=bool(pwd_raw),
        result_type=result_type,
    )


def guest_reply_thread(
    request,
    thread,
    *,
    body: str,
) -> tuple[bool, str]:
    """访客在已有主题下继续留言"""
    from .guestbook_models import GuestbookMessage
    from .guestbook_notify import notify_manager_new_guestbook

    if not is_thread_unlocked(request, thread):
        return False, '请先输入正确的查看密码'

    text = (body or '').strip()
    if len(text) < 2:
        return False, '请至少填写两个字'
    if len(text) > MAX_BODY:
        return False, f'留言请控制在 {MAX_BODY} 字以内'

    label = guest_display_label(request, thread.guest_display_name)
    msg = GuestbookMessage.objects.create(
        thread=thread,
        author_side='guest',
        author_label=label,
        body=text,
    )
    thread.last_activity_at = now_local_wall()
    thread.owner_read_at = None
    thread.save(update_fields=['last_activity_at', 'owner_read_at'])
    notify_manager_new_guestbook(thread, msg)
    return True, '已发送'


def owner_reply_thread(thread, *, body: str, manager_user) -> tuple[bool, str]:
    from .guestbook_models import GuestbookMessage
    from .guestbook_notify import notify_guest_on_owner_reply

    text = (body or '').strip()
    if len(text) < 2:
        return False, '回复请至少两个字'
    if len(text) > MAX_BODY:
        return False, f'回复请控制在 {MAX_BODY} 字以内'

    label = getattr(manager_user, 'username', '管理者') or '管理者'
    msg = GuestbookMessage.objects.create(
        thread=thread,
        author_side='owner',
        author_label=label[:MAX_NAME],
        body=text,
    )
    thread.last_activity_at = now_local_wall()
    thread.save(update_fields=['last_activity_at'])
    notify_guest_on_owner_reply(thread, msg)
    return True, '回复已发送'


def apply_guestbook_actor_cookie(request, response):
    new_actor = getattr(request, '_yc_new_guestbook_actor', None)
    if new_actor:
        from .guestbook_rate_helpers import GUESTBOOK_ACTOR_COOKIE

        response.set_cookie(
            GUESTBOOK_ACTOR_COOKIE, new_actor, max_age=60 * 60 * 24 * 365,
            httponly=True, samesite='Lax',
        )
    return response
