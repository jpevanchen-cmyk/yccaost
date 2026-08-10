# 探测本机系统时区（无 Django 依赖，供 settings 启动时调用）

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_WINDOWS_TO_IANA = {
    'Tokyo Standard Time': 'Asia/Tokyo',
    'China Standard Time': 'Asia/Shanghai',
    'Taipei Standard Time': 'Asia/Taipei',
    'Korea Standard Time': 'Asia/Seoul',
    'Singapore Standard Time': 'Asia/Singapore',
    'SE Asia Standard Time': 'Asia/Bangkok',
    'North Asia East Standard Time': 'Asia/Irkutsk',
    'UTC': 'UTC',
    'GMT Standard Time': 'Europe/London',
    'Pacific Standard Time': 'America/Los_Angeles',
    'Eastern Standard Time': 'America/New_York',
}

_FALLBACK_TZ = 'Asia/Shanghai'


def detect_system_timezone_name() -> str:
    """
    探测本机系统时区的 IANA 名。
    优先：YECAO_TIME_ZONE → tzlocal（若已装）→ Windows 注册表映射 → zoneinfo.key → 回落。
    """
    env = (os.environ.get('YECAO_TIME_ZONE') or '').strip()
    if env and _zoneinfo_ok(env):
        return env

    try:
        from tzlocal import get_localzone_name  # type: ignore

        name = (get_localzone_name() or '').strip()
        if name and _zoneinfo_ok(name):
            return name
    except Exception:
        pass

    win_name = _windows_timezone_key_name()
    if win_name:
        mapped = _WINDOWS_TO_IANA.get(win_name)
        if mapped and _zoneinfo_ok(mapped):
            return mapped

    try:
        local_tz = datetime.now().astimezone().tzinfo
        key = getattr(local_tz, 'key', None)
        if key and _zoneinfo_ok(str(key)):
            return str(key)
    except Exception:
        pass

    return _FALLBACK_TZ


def _zoneinfo_ok(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, Exception):
        return False


def _windows_timezone_key_name() -> str:
    if os.name != 'nt':
        return ''
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r'SYSTEM\CurrentControlSet\Control\TimeZoneInformation',
        ) as key:
            value, _ = winreg.QueryValueEx(key, 'TimeZoneKeyName')
            return str(value or '').strip()
    except OSError:
        return ''
