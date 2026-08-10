# V1 第 8 项：登录连续试密码暂锁 + 审计配合

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from .time_helpers import now_local_wall

from .audit_helpers import client_ip_from_request, write_audit_log
from .models import LoginGuardState

# 连续错 5 次 → 暂锁 60 分钟（与暂锁邮件 1 小时冷却一致）
LOGIN_GUARD_MAX_FAILURES = 5
LOGIN_GUARD_LOCK_MINUTES = 60

SCOPE_ECOSYSTEM = 'ecosystem'
SCOPE_SHOP_WORK = 'shop_work'


def _normalize_username(username: str) -> str:
    return (username or '').strip().lower()[:64]


def build_login_guard_key(
    request,
    scope: str,
    *,
    username: str = '',
    seller_id: str = '',
) -> str:
    """同一登录口 + IP + 账号（工作台含店铺）构成锁定键。"""
    ip = client_ip_from_request(request) or 'unknown'
    user_part = _normalize_username(username) or '-'
    if scope == SCOPE_SHOP_WORK:
        shop = (seller_id or '').strip()[:64] or '-'
        return f'{shop}|{ip}|{user_part}'
    return f'{ip}|{user_part}'


def _lock_message(locked_until) -> str:
    """白话提示：还要等多久。"""
    if not locked_until:
        return '登录尝试过多，请稍后再试。'
    now = now_local_wall()
    if locked_until <= now:
        return '登录尝试过多，请稍后再试。'
    mins = max(1, int((locked_until - now).total_seconds() + 59) // 60)
    return f'密码试错了太多次，请 {mins} 分钟后再试。'


def check_login_allowed(
    request,
    scope: str,
    *,
    username: str = '',
    seller_id: str = '',
) -> tuple[bool, str]:
    """是否允许继续试密码；不允许时返回白话原因。"""
    key = build_login_guard_key(
        request, scope, username=username, seller_id=seller_id,
    )
    entry = LoginGuardState.objects.filter(scope=scope, guard_key=key).first()
    if not entry or not entry.locked_until:
        return True, ''
    if entry.locked_until <= now_local_wall():
        entry.locked_until = None
        entry.fail_count = 0
        entry.save(update_fields=['locked_until', 'fail_count', 'updated_at'])
        return True, ''
    return False, _lock_message(entry.locked_until)


def clear_login_guard(
    request,
    scope: str,
    *,
    username: str = '',
    seller_id: str = '',
) -> None:
    """登录成功后清除失败计数。"""
    key = build_login_guard_key(
        request, scope, username=username, seller_id=seller_id,
    )
    LoginGuardState.objects.filter(scope=scope, guard_key=key).delete()


def _failure_count_message(fail_count: int) -> str:
    """未暂锁时：告诉用户已连续错几次、再错几次会锁。"""
    remaining = max(0, LOGIN_GUARD_MAX_FAILURES - fail_count)
    return (
        f'用户名或密码错误。（已连续错 {fail_count} 次，'
        f'再错 {remaining} 次将暂锁 {LOGIN_GUARD_LOCK_MINUTES} 分钟）'
    )


def record_login_failure(
    request,
    scope: str,
    *,
    username: str = '',
    seller_id: str = '',
) -> tuple[bool, str]:
    """
    记录一次失败；返回 (是否刚暂锁, 给页面看的白话提示)。
    """
    key = build_login_guard_key(
        request, scope, username=username, seller_id=seller_id,
    )
    entry, _ = LoginGuardState.objects.get_or_create(
        scope=scope,
        guard_key=key,
        defaults={'fail_count': 0},
    )
    entry.fail_count += 1
    if entry.fail_count >= LOGIN_GUARD_MAX_FAILURES:
        entry.locked_until = now_local_wall() + timedelta(minutes=LOGIN_GUARD_LOCK_MINUTES)
        entry.fail_count = 0
        entry.save(update_fields=['fail_count', 'locked_until', 'updated_at'])
        lock_msg = _lock_message(entry.locked_until)
        return True, (
            f'{lock_msg}（已连续错 {LOGIN_GUARD_MAX_FAILURES} 次，账户已暂锁）'
        )
    entry.save(update_fields=['fail_count', 'updated_at'])
    return False, _failure_count_message(entry.fail_count)


def audit_login_locked(
    request,
    *,
    scope: str,
    username: str = '',
    seller_id: str = '',
    portal_label: str = '',
) -> None:
    """暂锁拦截或刚触发暂锁时记审计。"""
    label = portal_label or ('店铺工作台' if scope == SCOPE_SHOP_WORK else '野草生态')
    write_audit_log(
        action_code='login_locked',
        summary=f'{label}登录暂锁：{username or "（未填用户名）"}',
        seller_id=seller_id or '',
        actor_username=username or '',
        result='fail',
        request=request,
    )


def handle_failed_login_attempt(
    request,
    scope: str,
    *,
    username: str = '',
    seller_id: str = '',
    portal_label: str = '',
    failed_summary: str = '',
) -> str:
    """
    统一处理一次登录失败：计数、可能暂锁、写 login_failed / login_locked 审计。
    返回给页面展示的白话错误（用户名密码错误或暂锁提示）。
    """
    just_locked, user_msg = record_login_failure(
        request, scope, username=username, seller_id=seller_id,
    )
    write_audit_log(
        action_code='login_failed',
        summary=failed_summary or f'登录失败：{username or "（未填用户名）"}',
        seller_id=seller_id or '',
        actor_username=username or '',
        result='fail',
        request=request,
    )
    if just_locked:
        audit_login_locked(
            request,
            scope=scope,
            username=username,
            seller_id=seller_id,
            portal_label=portal_label,
        )
        from .login_lock_notify_helpers import notify_login_locked_email

        notify_login_locked_email(
            scope=scope,
            username=username,
            seller_id=seller_id,
            portal_label=portal_label,
        )
    return user_msg
