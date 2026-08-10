# V1 / 店内局域网：把可访问主机写入允许名单（避免手机/局域网 IP 访问 400）

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings


def hostname_from_http_base(url: str) -> str | None:
    """从 http://192.168.x.x:8000 取出主机名；回环或空则返回 None。"""
    text = (url or '').strip()
    if not text:
        return None
    if '://' not in text:
        text = 'http://' + text
    try:
        host = (urlparse(text).hostname or '').strip().lower()
    except Exception:
        return None
    if not host or host in ('127.0.0.1', 'localhost', '::1') or host.startswith('127.'):
        return None
    return host


def ensure_host_in_django_allowed(host: str) -> None:
    """当前进程立刻放行该主机（托盘未重启也能用）。"""
    host = (host or '').strip().lower()
    if not host:
        return
    allowed = list(getattr(settings, 'ALLOWED_HOSTS', []) or [])
    if host not in allowed:
        allowed.append(host)
        settings.ALLOWED_HOSTS = allowed


def merge_host_into_dotenv(host: str, *, env_path: Path | None = None) -> bool:
    """
    把主机写入项目 .env 的 YECAO_ALLOWED_HOSTS（下次启动仍有效）。
    成功改写返回 True；无文件或失败返回 False。
    """
    host = (host or '').strip().lower()
    if not host:
        return False
    path = env_path or (Path(getattr(settings, 'BASE_DIR', Path('.'))) / '.env')
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        return False

    key = 'YECAO_ALLOWED_HOSTS'
    lines = text.splitlines()
    found = False
    new_lines: list[str] = []
    for line in lines:
        raw = line.strip()
        if raw.startswith('#') or '=' not in line:
            new_lines.append(line)
            continue
        k, _, val = line.partition('=')
        if k.strip() != key:
            new_lines.append(line)
            continue
        found = True
        parts = [p.strip() for p in val.split(',') if p.strip()]
        merged: list[str] = []
        for p in parts + [host]:
            if p and p not in merged:
                merged.append(p)
        new_lines.append(f'{key}={",".join(merged)}')
    if not found:
        if new_lines and new_lines[-1].strip():
            new_lines.append('')
        new_lines.append(f'{key}=localhost,127.0.0.1,{host}')

    out = '\n'.join(new_lines)
    if text.endswith('\n'):
        out += '\n'
    try:
        path.write_text(out, encoding='utf-8')
    except OSError:
        return False
    return True


def apply_lan_url_to_allowed_hosts(lan_url: str, *, persist_env: bool = True) -> str | None:
    """
    根据局域网根地址放行主机：当前进程；可选写入 .env。
    返回已放行的主机名；无需处理则 None。
    """
    host = hostname_from_http_base(lan_url)
    if not host:
        return None
    ensure_host_in_django_allowed(host)
    if persist_env:
        merge_host_into_dotenv(host)
    return host


def load_saved_lan_hosts_into_allowed() -> None:
    """启动时：把库里已存的 V1 / 堂食局域网主机补进 ALLOWED_HOSTS（不反复改 .env）。"""
    try:
        from .owner_helpers import get_site_settings

        site = get_site_settings()
        apply_lan_url_to_allowed_hosts(
            getattr(site, 'v1_lan_base_url', '') or '',
            persist_env=False,
        )
    except Exception:
        pass

    try:
        from .models import ShopProfile
        from .operating_helpers import get_operating_settings

        for seller_id in ShopProfile.objects.values_list('seller_id', flat=True)[:50]:
            op = get_operating_settings(seller_id)
            apply_lan_url_to_allowed_hosts(
                getattr(op, 'table_lan_base_url', '') or '',
                persist_env=False,
            )
    except Exception:
        pass
