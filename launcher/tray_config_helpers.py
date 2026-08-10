# 托盘启动器：项目路径、网页服务配置

from __future__ import annotations

import json
import os
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


def fetch_launcher_config(root: Path | None = None) -> dict:
    """通过 Django 管理命令读取端口与营业地址（服务未启动时也可读库）。"""
    root = root or project_root()
    py = python_executable(root)
    manage = root / 'manage.py'
    if not manage.is_file():
        return _fallback_config()
    try:
        proc = run_hidden(
            [str(py), str(manage), 'yecao_launcher_config'],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _fallback_config()
    if proc.returncode != 0:
        return _fallback_config()
    try:
        data = json.loads(proc.stdout.strip() or '{}')
    except json.JSONDecodeError:
        return _fallback_config()
    return {
        'listen_port': int(data.get('listen_port') or 8000),
        'open_url': (data.get('open_url') or '').strip() or 'http://127.0.0.1:8000/accounts/login/',
        'setup_completed': bool(data.get('setup_completed')),
        'v1_local_mode': bool(data.get('v1_local_mode')),
    }


def _fallback_config() -> dict:
    port = int(os.environ.get('YECAO_TRAY_PORT', '8000') or 8000)
    return {
        'listen_port': port,
        'open_url': f'http://127.0.0.1:{port}/accounts/login/',
        'setup_completed': False,
        'v1_local_mode': False,
    }


def runserver_command(root: Path, port: int) -> list[str]:
    py = python_executable(root)
    return [str(py), str(root / 'manage.py'), 'runserver', f'0.0.0.0:{port}', '--noreload']
