# 托盘：Windows 下隐藏 subprocess 黑窗口

from __future__ import annotations

import subprocess
import sys
from typing import Any


def subprocess_no_window_flags() -> int:
    """Windows 创建子进程时不弹出命令行窗口。"""
    if sys.platform == 'win32':
        return getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    return 0


def run_hidden(
    args,
    *,
    cwd: str | None = None,
    capture_output: bool = False,
    text: bool = False,
    timeout: float | None = None,
    check: bool = False,
    encoding: str | None = None,
    errors: str | None = None,
) -> subprocess.CompletedProcess:
    """与 subprocess.run 相同，但默认藏黑窗。"""
    kwargs: dict[str, Any] = {
        'cwd': cwd,
        'capture_output': capture_output,
        'text': text,
        'timeout': timeout,
        'check': check,
        'creationflags': subprocess_no_window_flags(),
    }
    if encoding is not None:
        kwargs['encoding'] = encoding
    if errors is not None:
        kwargs['errors'] = errors
    return subprocess.run(args, **kwargs)
