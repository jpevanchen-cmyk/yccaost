# V1 第 11 项：本机忘记密码重置（须能碰到装野草的那台电脑）

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model

from .audit_helpers import write_audit_log
from .models import LoginGuardState

User = get_user_model()

# 新密码最短长度（白话：别太短）
MIN_NEW_PASSWORD_LEN = 8
# 交互确认须原样输入
CONFIRM_PHRASE = '确认重置'


def list_owner_accounts() -> list[Any]:
    """可重置的老板账号（服务器管理者）。"""
    return list(
        User.objects.filter(is_server_owner=True, is_active=True)
        .order_by('username')
    )


def _clear_login_guards_for_username(username: str) -> None:
    """清掉该登录名相关的试密码暂锁计数。"""
    key_part = (username or '').strip().lower()
    if not key_part:
        return
    LoginGuardState.objects.filter(guard_key__icontains=key_part).delete()


def reset_owner_login_password(username: str, new_password: str) -> tuple[bool, str]:
    """
    重置老板网页登录密码，并尽量同步店主工牌密码。
    """
    name = (username or '').strip()
    password = new_password or ''
    if not name:
        return False, '请指定要重置的老板登录名。'
    if len(password) < MIN_NEW_PASSWORD_LEN:
        return False, f'新密码至少 {MIN_NEW_PASSWORD_LEN} 位。'

    user = User.objects.filter(username=name, is_server_owner=True, is_active=True).first()
    if user is None:
        return False, f'找不到老板账号「{name}」（须是服务器管理者且未停用）。'

    user.set_password(password)
    user.save(update_fields=['password'])

    # 店主工牌：登录名一般为 老板名::老板名，向导创建时与主账号同密
    from .staff_account_helpers import STAFF_ROLE, staff_internal_username

    staff_name = staff_internal_username(name, name)
    staff = User.objects.filter(
        username=staff_name,
        role=STAFF_ROLE,
        employer_seller_id=name,
        is_active=True,
    ).first()
    staff_note = ''
    if staff is not None:
        staff.set_password(password)
        staff.save(update_fields=['password'])
        staff_note = '；店主工牌密码已一并改成相同。'

    _clear_login_guards_for_username(name)
    if staff is not None:
        _clear_login_guards_for_username(staff_name)

    write_audit_log(
        action_code='other',
        summary=f'本机忘记密码工具：重置老板登录密码（{name}）',
        seller_id=name,
        actor_username='本机重置工具',
        result='ok',
        request=None,
    )
    return True, f'已重置老板「{name}」的登录密码{staff_note}'


def clear_tray_startup_exit_password() -> tuple[bool, str]:
    """清除托盘启动/退出密码（关掉保护，可稍后在托盘里重设）。"""
    try:
        from launcher.tray_password_helpers import clear_tray_password, password_is_configured
    except ImportError:
        return False, '找不到托盘密码模块，无法清除。'

    if not password_is_configured():
        return True, '托盘启动/退出密码本来就未开启，无需清除。'
    clear_tray_password()
    write_audit_log(
        action_code='other',
        summary='本机忘记密码工具：清除托盘启动/退出密码',
        seller_id='',
        actor_username='本机重置工具',
        result='ok',
        request=None,
    )
    return True, '已清除托盘启动/退出密码。请重新打开托盘后，可在菜单里重新设置。'


def clear_operation_lock_pin_local() -> tuple[bool, str]:
    """清除卖家后台操作锁 PIN（关掉操作锁）。"""
    from .operation_lock_helpers import clear_operation_lock_pin, operation_lock_configured
    from .owner_helpers import get_site_settings

    site = get_site_settings()
    if not operation_lock_configured(site):
        return True, '操作锁本来就未开启，无需清除。'
    clear_operation_lock_pin(site)
    site.save(
        update_fields=[
            'operation_lock_pin_salt',
            'operation_lock_pin_hash',
            'operation_lock_enabled',
            'updated_at',
        ],
    )
    write_audit_log(
        action_code='operation_lock',
        summary='本机忘记密码工具：清除操作锁 PIN',
        seller_id='',
        actor_username='本机重置工具',
        result='ok',
        request=None,
    )
    return True, '已清除操作锁。进入后台后可在设置里重新开启。'


def confirm_phrase_ok(text: str) -> bool:
    return (text or '').strip() == CONFIRM_PHRASE
