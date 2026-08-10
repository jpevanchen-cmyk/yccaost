# 托盘启动器：端口占用检查与清理（Windows 开发/V1 内测）

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .tray_subprocess_helpers import run_hidden


def list_listening_pids(port: int) -> list[int]:
    """列出正在监听指定 TCP 端口的进程号（Windows netstat）。"""
    if sys.platform != 'win32':
        return []
    try:
        proc = run_hidden(
            ['netstat', '-ano'],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    needle = f':{int(port)}'
    pids: set[int] = set()
    for line in (proc.stdout or '').splitlines():
        upper = line.upper()
        if 'LISTENING' not in upper:
            continue
        if needle not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            pids.add(int(parts[-1]))
        except ValueError:
            continue
    return sorted(pids)


def get_process_command_line(pid: int) -> str:
    """读取 Windows 进程命令行（读不到则返回空串）。"""
    if sys.platform != 'win32' or pid <= 0:
        return ''
    try:
        proc = run_hidden(
            [
                'powershell',
                '-NoProfile',
                '-Command',
                f'(Get-CimInstance Win32_Process -Filter "ProcessId={int(pid)}").CommandLine',
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return (proc.stdout or '').strip()


def command_line_is_yecao_runserver(cmdline: str, root: Path) -> bool:
    """命令行是否为本项目 manage.py runserver。"""
    if not cmdline:
        return False
    lower = cmdline.lower()
    if 'runserver' not in lower or 'manage.py' not in lower:
        return False
    manage = str((root / 'manage.py').resolve()).lower().replace('\\', '/')
    normalized = lower.replace('\\', '/')
    if manage in normalized:
        return True
    root_text = str(root.resolve()).lower().replace('\\', '/')
    return root_text in normalized and 'runserver' in normalized


def yecao_runserver_pids_on_port(port: int, root: Path) -> list[int]:
    """占用端口的野草 runserver 进程号。"""
    matched: list[int] = []
    for pid in list_listening_pids(port):
        if command_line_is_yecao_runserver(get_process_command_line(pid), root):
            matched.append(pid)
    return matched


def list_direct_child_pids(parent_pid: int) -> list[int]:
    """列出某进程的直接子进程号（读不到则空）。"""
    if sys.platform != 'win32' or parent_pid <= 0:
        return []
    try:
        proc = run_hidden(
            [
                'powershell',
                '-NoProfile',
                '-Command',
                (
                    f'Get-CimInstance Win32_Process -Filter "ParentProcessId={int(parent_pid)}" '
                    f'| Select-Object -ExpandProperty ProcessId'
                ),
            ],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    out: list[int] = []
    for line in (proc.stdout or '').splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            out.append(int(text))
        except ValueError:
            continue
    return out


def protect_pids_for_owned_server(owned_pid: int | None) -> set[int]:
    """
    当前托盘自己拉起的服务：自身进程号 + 直接子进程，检查端口时不得结束。
    """
    protect: set[int] = set()
    if not owned_pid or owned_pid <= 0:
        return protect
    protect.add(int(owned_pid))
    for child in list_direct_child_pids(int(owned_pid)):
        protect.add(child)
    return protect


def foreign_listeners_on_port(port: int, exclude_pids: set[int] | None = None) -> list[int]:
    """占用端口的进程（可排除指定 pid，例如本托盘刚起的子进程）。"""
    exclude = exclude_pids or set()
    return [pid for pid in list_listening_pids(port) if pid not in exclude]


def format_port_busy_message(port: int, pids: list[int], root: Path) -> str:
    """启动被拦时给用户的白话说明。"""
    if not pids:
        return f'端口 {port} 已被占用，请先关闭旧的服务器再启动。'
    lines = [f'端口 {port} 已被占用，无法再开一个网页服务。']
    yecao = yecao_runserver_pids_on_port(port, root)
    if yecao:
        lines.append(f'检测到野草 runserver 进程：{", ".join(str(p) for p in yecao)}')
        lines.append('请打开托盘菜单「检查端口占用…」清理，或在任务管理器结束对应 python.exe。')
    else:
        lines.append(f'占用进程号：{", ".join(str(p) for p in pids)}（可能不是野草，请自行确认后再关）')
    return '\n'.join(lines)


def describe_port_listeners(
    port: int,
    root: Path,
    *,
    protect_pids: set[int] | None = None,
) -> tuple[str, list[int]]:
    """
    托盘菜单用：汇总端口占用。
    返回 (说明文字, 可安全结束的野草 runserver pid)。
    当前托盘自己的服务在 protect_pids 内，不会进入可结束名单。
    """
    protect = set(protect_pids or set())
    pids = list_listening_pids(port)
    if not pids:
        return f'端口 {port} 当前空闲，没有进程在监听。', []

    yecao = yecao_runserver_pids_on_port(port, root)
    own = sorted(pid for pid in yecao if pid in protect)
    others = sorted(pid for pid in yecao if pid not in protect)

    lines = [f'端口 {port} 监听进程：{", ".join(str(p) for p in pids)}']
    if own:
        lines.append(
            f'其中当前托盘正在使用的服务：{", ".join(str(p) for p in own)}（不会结束）'
        )
    if others:
        lines.append(f'其它野草 runserver（可清理）：{", ".join(str(p) for p in others)}')
    elif yecao and own and not others:
        lines.append('没有发现需要清理的其它野草进程。')
    elif not yecao:
        lines.append('未发现本项目的 manage.py runserver（可能是其它程序占用）。')
    return '\n'.join(lines), others


def stop_runserver_pids(pids: list[int]) -> tuple[bool, str]:
    """结束指定进程号（仅调用方确认是 runserver 后再传）。"""
    if sys.platform != 'win32':
        return False, '当前系统不支持自动结束进程。'
    if not pids:
        return True, '没有需要结束的进程。'
    stopped: list[int] = []
    failed: list[int] = []
    for pid in pids:
        try:
            proc = run_hidden(
                ['taskkill', '/PID', str(pid), '/F'],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            failed.append(pid)
            continue
        if proc.returncode == 0:
            stopped.append(pid)
        else:
            failed.append(pid)
    parts: list[str] = []
    if stopped:
        parts.append(f'已结束进程：{", ".join(str(p) for p in stopped)}')
    if failed:
        parts.append(f'未能结束：{", ".join(str(p) for p in failed)}')
    ok = not failed
    return ok, '\n'.join(parts) if parts else '未执行任何操作。'
