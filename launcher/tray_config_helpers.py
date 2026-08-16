# 托盘启动器：项目路径、网页服务配置、店内地址（与堂食同一套）

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def python_executable(root: Path | None = None) -> Path:
    root = root or project_root()
    venv_py = root / '.venv' / 'Scripts' / 'python.exe'
    if venv_py.is_file():
        return venv_py
    return Path(sys.executable)


def _parse_launcher_payload(data: dict) -> dict:
    port = int(data.get('listen_port') or 8000)
    open_url = (data.get('open_url') or '').strip() or f'http://127.0.0.1:{port}/accounts/login/'
    msg = (data.get('lan_message') or data.get('message') or '').strip()
    payload = {
        'listen_port': port,
        'open_url': open_url,
        'lan_base_url': (data.get('lan_base_url') or data.get('saved_lan') or '').strip(),
        'detected_lan': (data.get('detected_lan') or '').strip(),
        'match': bool(data.get('match')),
        'detect_failed': bool(data.get('detect_failed')),
        'lan_message': msg,
        'setup_completed': bool(data.get('setup_completed')),
        'v1_local_mode': bool(data.get('v1_local_mode')),
        'ok': data.get('ok'),
        'message': (data.get('message') or msg),
    }
    return payload


def _empty_fail(message: str) -> dict:
    """问不到时的人话结果，禁止当成检测成功。"""
    port = int(os.environ.get('YECAO_TRAY_PORT', '8000') or 8000)
    return {
        'listen_port': port,
        'open_url': f'http://127.0.0.1:{port}/accounts/login/',
        'lan_base_url': '',
        'detected_lan': '',
        'match': False,
        'detect_failed': True,
        'lan_message': message,
        'setup_completed': False,
        'v1_local_mode': False,
        'ok': False,
        'message': message,
    }


def _ensure_django(root: Path) -> None:
    """控制台进程内加载同一套后台（后台还没起来时用）。"""
    from django.conf import settings as dj_settings

    if dj_settings.configured:
        return
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wuwei_system.settings')
    import django

    django.setup()


def _lan_via_django(root: Path, *, apply: bool) -> dict:
    """与堂食营业同一套函数：对比或写入。"""
    _ensure_django(root)
    from waimai.lan_base_helpers import (
        apply_detected_lan_base_url,
        compare_saved_and_detected,
        local_open_backend_url,
    )
    from waimai.owner_helpers import get_site_settings
    from waimai.v1_local_helpers import v1_local_mode_enabled

    if apply:
        ok, msg, snap = apply_detected_lan_base_url()
        snap['ok'] = ok
        snap['message'] = msg
    else:
        snap = compare_saved_and_detected()
        snap['ok'] = True
    site = get_site_settings()
    port = int(snap.get('listen_port') or 8000)
    return _parse_launcher_payload({
        'listen_port': port,
        'open_url': local_open_backend_url(port),
        'lan_base_url': snap.get('saved_lan') or '',
        'detected_lan': snap.get('detected_lan') or '',
        'match': snap.get('match'),
        'detect_failed': snap.get('detect_failed'),
        'lan_message': snap.get('message') or '',
        'setup_completed': bool(site.v1_setup_completed),
        'v1_local_mode': v1_local_mode_enabled(),
        'ok': snap.get('ok'),
        'message': snap.get('message') or '',
    })


def _try_http_lan(port: int, method: str) -> dict | None:
    """问正在跑的本机后台（与堂食同一进程）。连不上则返回 None。"""
    url = f'http://127.0.0.1:{int(port)}/v1-local/tray/lan/'
    req = Request(
        url,
        method=method,
        headers={
            'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        },
    )
    if method == 'POST':
        req.data = b''
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    try:
        with urlopen(req, timeout=20) as resp:
            raw = (resp.read() or b'').decode('utf-8', errors='replace')
            status = getattr(resp, 'status', 200)
    except HTTPError as exc:
        raw = (exc.read() or b'').decode('utf-8', errors='replace')
        status = exc.code
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        parsed = _parse_launcher_payload(data)
        if status >= 400:
            parsed['ok'] = False
            if not parsed.get('lan_message'):
                parsed['lan_message'] = parsed.get('message') or '本机后台拒绝了这次请求。'
                parsed['message'] = parsed['lan_message']
        return parsed
    except (URLError, TimeoutError, OSError, ValueError):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data:
        return None
    parsed = _parse_launcher_payload(data)
    parsed['ok'] = data.get('ok', True)
    return parsed


def fetch_launcher_config(root: Path | None = None, listen_port: int | None = None) -> dict:
    """优先问正在跑的本机后台；问不到再在控制台进程内走同一套函数。"""
    root = root or project_root()
    port = int(listen_port or os.environ.get('YECAO_TRAY_PORT') or 8000)
    via_http = _try_http_lan(port, 'GET')
    if via_http is not None:
        return via_http
    try:
        return _lan_via_django(root, apply=False)
    except Exception:
        return _empty_fail(
            '没有问到店内地址。请确认本机后台已启动，或到堂食营业里查看。'
        )


def apply_detected_lan_from_tray(root: Path | None = None, listen_port: int | None = None) -> dict:
    """托盘确认后写入：与堂食「一键更新」同一套。"""
    root = root or project_root()
    port = int(listen_port or os.environ.get('YECAO_TRAY_PORT') or 8000)
    via_http = _try_http_lan(port, 'POST')
    if via_http is not None:
        return via_http
    try:
        return _lan_via_django(root, apply=True)
    except Exception:
        return _empty_fail(
            '没能更新店内地址。请到堂食营业里一键更新，或确认本机后台已启动。'
        )


def runserver_command(root: Path, port: int) -> list[str]:
    py = python_executable(root)
    return [str(py), str(root / 'manage.py'), 'runserver', f'0.0.0.0:{port}', '--noreload']
