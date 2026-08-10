# V1 首次向导：本机弹出「选择文件夹」（绝对路径，供备份目录）
# 浏览器无法直接给出盘符路径，故用本机对话框；与托盘选夹同类。

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def pick_backup_directory(*, initial_dir: str = '') -> str | None:
    """
    弹出系统选文件夹框。选中返回绝对路径；取消或失败返回 None。
    用独立子进程，避免网站工作线程里直接开窗口不稳定。
    """
    start = (initial_dir or '').strip()
    if start and not Path(start).is_dir():
        start = ''
    # 子进程内弹窗；路径经标准输出一行返回
    script = (
        'import sys\n'
        'from tkinter import Tk, filedialog\n'
        'root = Tk()\n'
        'root.withdraw()\n'
        'root.attributes("-topmost", True)\n'
        'kwargs = {"title": "选择备份目录", "mustexist": True}\n'
        'start = sys.argv[1] if len(sys.argv) > 1 else ""\n'
        'if start:\n'
        '    kwargs["initialdir"] = start\n'
        'chosen = filedialog.askdirectory(**kwargs) or ""\n'
        'root.destroy()\n'
        'print(chosen)\n'
    )
    try:
        proc = subprocess.run(
            [sys.executable, '-c', script, start],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (proc.stdout or '').strip().splitlines()
    path = (text[-1] if text else '').strip()
    if not path:
        return None
    return str(Path(path))
