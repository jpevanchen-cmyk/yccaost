# 同一安装目录只允许一个托盘（禁止多开）

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

# Windows：CreateMutex 已存在
_ERROR_ALREADY_EXISTS = 183


def mutex_name_for_install(root: Path) -> str:
    """按安装目录生成互斥体名（不同目录互不影响）。"""
    resolved = str(root.resolve()).lower().replace('\\', '/')
    digest = hashlib.sha256(resolved.encode('utf-8')).hexdigest()[:16]
    return f'Local\\YecaoST_Tray_{digest}'


def show_window_flag_path(root: Path) -> Path:
    """第二实例请求「亮起状态窗口」时写入的标记文件。"""
    return root / 'launcher' / 'tray_show_window.flag'


def request_show_existing_window(root: Path) -> None:
    """通知已在运行的托盘打开状态窗口。"""
    path = show_window_flag_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()), encoding='utf-8')
    except OSError:
        pass


def consume_show_window_request(root: Path) -> bool:
    """若有「请显示窗口」请求则清除并返回 True。"""
    path = show_window_flag_path(root)
    if not path.is_file():
        return False
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


class InstallSingleInstanceLock:
    """
    Windows 下用命名互斥体锁住本安装目录。
    非 Windows 或创建失败时视为未加锁（调用方自行决定）。
    """

    def __init__(self, root: Path):
        self.root = root
        self._handle = None
        self._name = mutex_name_for_install(root)

    def try_acquire(self) -> bool:
        """抢到锁返回 True；已有实例返回 False。"""
        if sys.platform != 'win32':
            return True
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.CreateMutexW(None, False, self._name)
            if not handle:
                return True
            already = kernel32.GetLastError() == _ERROR_ALREADY_EXISTS
            if already:
                kernel32.CloseHandle(handle)
                return False
            self._handle = handle
            return True
        except Exception:
            return True

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._handle)
        except Exception:
            pass
        self._handle = None
