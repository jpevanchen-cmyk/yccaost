# 托盘启动器：项目路径、网页服务配置

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .tray_subprocess_helpers import run_hidden


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


def _fallback_config() -> dict:
    port = int(os.environ.get('YECAO_TRAY_PORT', '8000') or 8000)
    return {
        'listen_port': port,
        'open_url': f'http://127.0.0.1:{port}/accounts/login/',
        'lan_base_url': '',
        'detected_lan': '',
        'match': False,
        'detect_failed': True,
        'lan_message': '暂时读不到配置，本机仍可尝试打开后台。',
        'setup_completed': False,
        'v1_local_mode': False,
    }


def _run_manage(root: Path, *args: str, timeout: int = 60) -> dict:
    py = python_executable(root)
    manage = root / 'manage.py'
    if not manage.is_file():
        return _fallback_config()
    try:
        proc = run_hidden(
            [str(py), str(manage), *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _fallback_config()
    try:
        data = json.loads((proc.stdout or '').strip() or '{}')
    except json.JSONDecodeError:
        return _fallback_config()
    if not isinstance(data, dict):
        return _fallback_config()
    return _parse_launcher_payload(data)


def fetch_launcher_config(root: Path | None = None) -> dict:
    """通过 Django 管理命令读取端口、本机打开后台与店内地址对比。"""
    root = root or project_root()
    return _run_manage(root, 'yecao_launcher_config')


def apply_detected_lan_from_tray(root: Path | None = None) -> dict:
    """托盘确认后：把当前探测写入堂食真源。"""
    root = root or project_root()
    raw = _run_manage(root, 'yecao_lan_apply', timeout=90)
    # 一键命令回的是 saved_lan / message；这里对齐成托盘配置字段
    return raw


def runserver_command(root: Path, port: int) -> list[str]:
    py = python_executable(root)
    return [str(py), str(root / 'manage.py'), 'runserver', f'0.0.0.0:{port}', '--noreload']
