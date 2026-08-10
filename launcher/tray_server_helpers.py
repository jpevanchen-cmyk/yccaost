# 托盘启动器：后台网页服务子进程

from __future__ import annotations

import atexit
import os
import subprocess
import sys
import time
from pathlib import Path

from .tray_config_helpers import fetch_launcher_config, project_root, runserver_command
from .tray_job_helpers import assign_process_to_job, close_job_handle, create_kill_on_close_job
from .tray_port_helpers import foreign_listeners_on_port, format_port_busy_message
from .tray_subprocess_helpers import run_hidden


class TrayServerProcess:
    """管理 runserver 子进程（V1 内测；正式交付可换 waitress）。"""

    def __init__(self, root: Path | None = None):
        self.root = root or project_root()
        self._proc: subprocess.Popen | None = None
        self._port = 8000
        self._job_handle = create_kill_on_close_job()
        atexit.register(self._atexit_stop)

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def port(self) -> int:
        return self._port

    @property
    def child_pid(self) -> int | None:
        """当前托盘拉起的网页服务进程号（未运行则为 None）。"""
        return self._child_pid()

    def _atexit_stop(self) -> None:
        """解释器正常退出时尽量停掉子进程（作业对象负责异常强杀场景）。"""
        if self.running:
            try:
                self.stop()
            except Exception:
                pass

    def _child_pid(self) -> int | None:
        if not self._proc:
            return None
        return self._proc.pid

    def start(self) -> tuple[bool, str]:
        if self.running:
            return True, '网页服务已在运行'
        cfg = fetch_launcher_config(self.root)
        self._port = int(cfg.get('listen_port') or 8000)

        exclude = {os.getpid()}
        child_pid = self._child_pid()
        if child_pid:
            exclude.add(child_pid)
        busy_pids = foreign_listeners_on_port(self._port, exclude_pids=exclude)
        if busy_pids:
            return False, format_port_busy_message(self._port, busy_pids, self.root)

        if self._job_handle is None:
            self._job_handle = create_kill_on_close_job()

        cmd = runserver_command(self.root, self._port)
        creationflags = 0
        if sys.platform == 'win32':
            creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(self.root),
                creationflags=creationflags,
            )
        except OSError as exc:
            self._proc = None
            return False, f'无法启动网页服务：{exc}'

        if sys.platform == 'win32' and self._proc._handle:
            assign_process_to_job(self._job_handle, int(self._proc._handle))

        time.sleep(1.2)
        if not self.running:
            if self._proc is not None:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            self._proc = None
            close_job_handle(self._job_handle)
            self._job_handle = create_kill_on_close_job()
            return False, '网页服务启动后立即退出，请用托盘菜单「检查端口占用…」查看是否端口被占。'
        return True, f'网页服务已启动（端口 {self._port}）'

    def stop(self) -> tuple[bool, str]:
        if not self._proc:
            close_job_handle(self._job_handle)
            self._job_handle = create_kill_on_close_job()
            return True, '网页服务未在运行'
        proc = self._proc
        self._proc = None
        if proc.poll() is not None:
            close_job_handle(self._job_handle)
            self._job_handle = create_kill_on_close_job()
            return True, '网页服务已停止'
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
        close_job_handle(self._job_handle)
        self._job_handle = create_kill_on_close_job()
        return True, '网页服务已停止'

    def run_exit_backup(self) -> tuple[bool, str]:
        """正常退出前稳定备份（服务仍在跑，用 SQLite online backup）。"""
        from .tray_config_helpers import python_executable

        py = python_executable(self.root)
        manage = self.root / 'manage.py'
        if not manage.is_file():
            return True, '跳过备份（未找到 manage.py）'
        try:
            proc = run_hidden(
                [str(py), str(manage), 'yecao_backup_on_exit'],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f'退出备份未完成：{exc}'
        msg = (proc.stdout or proc.stderr or '').strip().splitlines()
        tail = msg[-1] if msg else '退出备份已执行'
        return proc.returncode == 0, tail
