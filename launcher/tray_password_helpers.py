# 托盘层：可选启动/退出密码（默认关；最小化不要密码）

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from pathlib import Path

SETTINGS_FILE = Path(__file__).resolve().parent / 'tray_local_settings.json'
_PBKDF2_ITERS = 200_000


def _default_settings() -> dict:
    return {
        'startup_password_enabled': False,
        'exit_password_enabled': False,
        'password_salt': '',
        'password_hash': '',
    }


def load_tray_password_settings() -> dict:
    if not SETTINGS_FILE.is_file():
        return _default_settings()
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return _default_settings()
    base = _default_settings()
    base.update({k: data.get(k, base[k]) for k in base})
    return base


def save_tray_password_settings(data: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def _hash_password(plain: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac(
        'sha256',
        plain.encode('utf-8'),
        salt,
        _PBKDF2_ITERS,
    )
    return base64.b64encode(digest).decode('ascii')


def password_is_configured(settings: dict | None = None) -> bool:
    settings = settings or load_tray_password_settings()
    return bool(settings.get('password_hash') and settings.get('password_salt'))


def set_tray_password(
    plain: str,
    *,
    startup_enabled: bool,
    exit_enabled: bool,
) -> None:
    salt = secrets.token_bytes(16)
    data = load_tray_password_settings()
    data['password_salt'] = base64.b64encode(salt).decode('ascii')
    data['password_hash'] = _hash_password(plain, salt)
    data['startup_password_enabled'] = bool(startup_enabled)
    data['exit_password_enabled'] = bool(exit_enabled)
    save_tray_password_settings(data)


def apply_tray_password_settings(
    *,
    startup_enabled: bool,
    exit_enabled: bool,
    new_password: str = '',
    old_password: str = '',
) -> tuple[bool, str]:
    """
    控制台保存启动/退出密码。
    · 启动、退出都不勾 = 关闭密码
    · 至少勾一项：填了新密码则改密；留空且已有密码则只改开关
    · 已有密码时改设置须先验旧密码
    """
    startup_enabled = bool(startup_enabled)
    exit_enabled = bool(exit_enabled)
    new_password = (new_password or '').strip()
    old_password = old_password or ''

    if password_is_configured():
        if not verify_tray_password(old_password):
            return False, '当前密码不正确。'

    if not startup_enabled and not exit_enabled:
        clear_tray_password()
        return True, '已关闭启动/退出密码。'

    if new_password:
        if len(new_password) < 6:
            return False, '新密码至少 6 位。'
        set_tray_password(
            new_password,
            startup_enabled=startup_enabled,
            exit_enabled=exit_enabled,
        )
        return True, '密码设置已保存。'

    if not password_is_configured():
        return False, '请先填写至少 6 位新密码。'

    data = load_tray_password_settings()
    data['startup_password_enabled'] = startup_enabled
    data['exit_password_enabled'] = exit_enabled
    save_tray_password_settings(data)
    return True, '已更新启动/退出密码开关。'


def clear_tray_password() -> None:
    save_tray_password_settings(_default_settings())


def verify_tray_password(plain: str, settings: dict | None = None) -> bool:
    settings = settings or load_tray_password_settings()
    if not password_is_configured(settings):
        return True
    try:
        salt = base64.b64decode(settings['password_salt'])
        expected = settings['password_hash']
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(_hash_password(plain, salt), expected)


def startup_password_required(settings: dict | None = None) -> bool:
    settings = settings or load_tray_password_settings()
    return bool(settings.get('startup_password_enabled') and password_is_configured(settings))


def exit_password_required(settings: dict | None = None) -> bool:
    settings = settings or load_tray_password_settings()
    return bool(settings.get('exit_password_enabled') and password_is_configured(settings))
