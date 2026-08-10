# 托盘：启动自检、定时备份、恢复

from __future__ import annotations

import json
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path

from .tray_config_helpers import python_executable
from .tray_subprocess_helpers import run_hidden


def _manage_py(root: Path) -> Path:
    return root / 'manage.py'


def _run_manage(root: Path, *args: str, timeout: float = 600) -> subprocess.CompletedProcess:
    py = python_executable(root)
    manage = _manage_py(root)
    return run_hidden(
        [str(py), str(manage), *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=timeout,
        check=False,
    )


def _append_tray_log(root: Path, title: str, body: str) -> None:
    """把技术细节写入日志文件，不弹给用户。"""
    log_dir = root / 'logs'
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / 'tray_startup.log'
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with path.open('a', encoding='utf-8') as fh:
            fh.write(f'\n===== {stamp} {title} =====\n')
            fh.write((body or '').rstrip() + '\n')
    except OSError:
        pass


def _looks_like_traceback(text: str) -> bool:
    t = text or ''
    return 'Traceback' in t or '.py"' in t or t.count('\n') > 4


def _plain_user_text(text: str, fallback: str) -> str:
    raw = (text or '').strip()
    if not raw or _looks_like_traceback(raw):
        return fallback
    if len(raw) > 120:
        return fallback
    return raw


def _scan_latest_backup_file(root: Path, backup_dir: str = '') -> str:
    """不经过数据库：在备份目录找最新 yecao_db_*.sqlite3。"""
    candidates: list[Path] = []
    if backup_dir.strip():
        candidates.append(Path(backup_dir.strip()))
    candidates.append(root / 'backup')
    seen: set[str] = set()
    for directory in candidates:
        key = str(directory.resolve()) if directory.exists() else str(directory)
        if key in seen:
            continue
        seen.add(key)
        if not directory.is_dir():
            continue
        files = sorted(
            directory.glob('yecao_db_*.sqlite3'),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if files:
            return str(files[0])
    return ''


def fetch_startup_db_report(root: Path) -> dict:
    proc = _run_manage(root, 'yecao_startup_db_check', timeout=120)
    stderr = (proc.stderr or '').strip()
    stdout = (proc.stdout or '').strip()
    if stderr:
        _append_tray_log(root, '启动自检 stderr', stderr)

    report: dict = {}
    if stdout:
        # 命令可能在 stderr 写了堆栈，但仍在 stdout 输出了 JSON
        try:
            # 取最后一行 JSON（避免混入其它输出）
            last_line = stdout.splitlines()[-1]
            report = json.loads(last_line)
        except json.JSONDecodeError:
            try:
                report = json.loads(stdout)
            except json.JSONDecodeError:
                report = {}

    if report:
        if not report.get('ok'):
            tech = (report.get('tech_detail') or stderr or '').strip()
            if tech:
                _append_tray_log(root, '启动自检 tech_detail', tech)
            detail = _plain_user_text(
                str(report.get('user_message') or report.get('detail') or ''),
                '营业数据检查未通过。',
            )
            report['detail'] = detail
            report['user_message'] = detail
            if not (report.get('latest_backup') or '').strip():
                report['latest_backup'] = _scan_latest_backup_file(
                    root,
                    str(report.get('backup_dir') or ''),
                )
        return report

    # 完全没有可用 JSON：写日志 + 本地扫备份 + 白话说明
    _append_tray_log(
        root,
        '启动自检失败（无 JSON）',
        f'returncode={proc.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}',
    )
    latest = _scan_latest_backup_file(root)
    return {
        'ok': False,
        'detail': '营业数据检查未通过。',
        'user_message': '营业数据检查未通过。',
        'latest_backup': latest,
        'abnormal_shutdown_suspected': False,
    }


def run_backup_restore_latest(root: Path) -> tuple[bool, str]:
    proc = _run_manage(root, 'yecao_backup_restore', '--latest', timeout=900)
    raw = (proc.stdout or proc.stderr or '').strip()
    if proc.returncode != 0:
        _append_tray_log(root, '恢复失败', raw)
        return False, _plain_user_text(raw.splitlines()[-1] if raw else '', '从备份恢复失败，请查看日志。')
    msg = raw.splitlines()
    tail = msg[-1] if msg else '恢复命令已执行'
    return True, _plain_user_text(tail, '已完成恢复。')


def mark_tray_startup_running(root: Path) -> None:
    _run_manage(root, 'yecao_startup_mark', timeout=30)


def warn_abnormal_shutdown_ok() -> None:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    messagebox.showwarning(
        '野草 · 启动提醒',
        '上次可能未正常退出。\n'
        '本次已检查数据库，目前看起来正常。\n'
        '建议确认备份目录里有最新副本。',
        parent=root,
    )
    root.destroy()


def ask_restore_database(report: dict) -> bool:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    detail = _plain_user_text(
        str(report.get('user_message') or report.get('detail') or ''),
        '营业数据文件已损坏，无法正常读取。',
    )
    latest = (report.get('latest_backup') or '').strip()
    text = (
        '数据库可能已损坏，无法正常营业。\n'
        f'{detail}\n\n'
        f'最近备份：\n{latest}\n\n'
        '是否用这份备份恢复？\n（会先保留当前损坏文件）'
    )
    answer = messagebox.askyesno('野草 · 数据库异常', text, parent=root)
    root.destroy()
    return answer


def ask_force_start_without_backup() -> bool:
    """已废弃：坏库未恢复时禁止启动。保留函数名以免旧引用报错。"""
    return False


def show_error(title: str, message: str, parent=None) -> None:
    import tkinter as tk
    from tkinter import messagebox

    own = parent is None
    if own:
        parent = tk.Tk()
        parent.withdraw()
        parent.attributes('-topmost', True)
    messagebox.showerror(title, _plain_user_text(message, '操作失败，请查看日志。'), parent=parent)
    if own:
        parent.destroy()


def show_warning(title: str, message: str, parent=None) -> None:
    import tkinter as tk
    from tkinter import messagebox

    own = parent is None
    if own:
        parent = tk.Tk()
        parent.withdraw()
        parent.attributes('-topmost', True)
    messagebox.showwarning(title, message, parent=parent)
    if own:
        parent.destroy()


def show_info(title: str, message: str, parent=None) -> None:
    import tkinter as tk
    from tkinter import messagebox

    own = parent is None
    if own:
        parent = tk.Tk()
        parent.withdraw()
        parent.attributes('-topmost', True)
    messagebox.showinfo(title, message, parent=parent)
    if own:
        parent.destroy()


def ask_backup_destination_dir(parent=None) -> str | None:
    """弹出文件夹选择框；取消返回 None。"""
    import tkinter as tk
    from tkinter import filedialog

    own = parent is None
    if own:
        parent = tk.Tk()
        parent.withdraw()
        parent.attributes('-topmost', True)
    chosen = filedialog.askdirectory(
        parent=parent,
        title='选择备份保存文件夹',
        mustexist=True,
    )
    if own:
        parent.destroy()
    text = (chosen or '').strip()
    return text or None


def run_backup_to_directory(root: Path, dest_dir: str) -> tuple[bool, str]:
    """立刻备份到指定文件夹（调用 manage 命令）。"""
    proc = _run_manage(
        root,
        'yecao_backup_run',
        '--dest-dir',
        dest_dir,
        '--reason=export',
        timeout=900,
    )
    lines = (proc.stdout or proc.stderr or '').strip().splitlines()
    tail = lines[-1] if lines else '备份命令已执行'
    if proc.returncode != 0:
        _append_tray_log(root, '立刻备份失败', (proc.stdout or '') + '\n' + (proc.stderr or ''))
        return False, _plain_user_text(tail, '备份失败，请查看日志。')
    return True, tail


def backup_to_chosen_folder(root: Path, parent=None) -> None:
    """托盘菜单：选文件夹 → 立刻备份 → 弹窗说明结果。"""
    dest = ask_backup_destination_dir(parent=parent)
    if not dest:
        return
    ok, msg = run_backup_to_directory(root, dest)
    if ok:
        show_info('备份完成', msg, parent=parent)
    else:
        show_error('备份失败', msg, parent=parent)


def prepare_database_for_startup(root: Path) -> tuple[bool, str]:
    """
    启动服务前：自检，必要时恢复。
    库损坏且未成功恢复时禁止启动（不再提供强行启动）。
    返回 (可否启动, 说明)。
    """
    report = fetch_startup_db_report(root)
    if report.get('ok') and report.get('abnormal_shutdown_suspected'):
        warn_abnormal_shutdown_ok()

    if report.get('ok'):
        return True, '数据库自检通过'

    latest = (report.get('latest_backup') or '').strip()
    if latest and ask_restore_database(report):
        ok, msg = run_backup_restore_latest(root)
        if not ok:
            show_error('恢复失败', msg)
            return False, msg
        report = fetch_startup_db_report(root)
        if report.get('ok'):
            return True, '已从备份恢复，数据库自检通过'
        show_error(
            '恢复后仍异常',
            _plain_user_text(
                str(report.get('user_message') or report.get('detail') or ''),
                '恢复后数据库仍异常，请查看日志或联系维护。',
            ),
        )
        return False, '恢复后数据库仍异常'

    detail = _plain_user_text(
        str(report.get('user_message') or report.get('detail') or ''),
        '营业数据检查未通过。',
    )
    if not latest:
        show_error(
            '野草 · 无法启动',
            f'{detail}\n'
            '未找到可用备份，已禁止启动。\n'
            '请维护者用命令指定完好备份恢复后再开托盘。',
        )
        return False, '无可用备份，已禁止启动'

    show_error(
        '野草 · 无法启动',
        f'{detail}\n'
        '未从备份恢复，已禁止启动。\n'
        '请重新打开托盘并选择恢复，或由维护者命令恢复。',
    )
    return False, '用户未恢复，已禁止启动'


def fetch_backup_health_report(root: Path, *, limit: int = 10) -> dict:
    """调用抽检命令；失败时返回空安全结果。"""
    proc = _run_manage(
        root,
        'yecao_backup_health_check',
        f'--limit={int(limit)}',
        timeout=600,
    )
    stderr = (proc.stderr or '').strip()
    stdout = (proc.stdout or '').strip()
    if stderr:
        _append_tray_log(root, '备份抽检 stderr', stderr)
    if not stdout:
        return {'all_ok': True, 'checked': 0, 'message': '', 'bad_names': []}
    try:
        last = stdout.splitlines()[-1]
        data = json.loads(last)
    except json.JSONDecodeError:
        _append_tray_log(root, '备份抽检 JSON 异常', stdout)
        return {'all_ok': True, 'checked': 0, 'message': '', 'bad_names': []}
    return data if isinstance(data, dict) else {'all_ok': True, 'checked': 0, 'message': ''}


def notify_backup_health_if_bad(report: dict, *, via_icon=None) -> None:
    """抽检有坏备份时通知；优先托盘气泡，否则弹窗。"""
    if not report or report.get('all_ok', True):
        return
    msg = (report.get('message') or '').strip() or '最近备份中有文件不完整，请尽快另存一份。'
    if via_icon is not None:
        try:
            via_icon.notify(msg[:200], '野草 · 备份抽检')
            return
        except Exception:
            pass
    show_warning('野草 · 备份抽检', msg)


def run_scheduled_backup_if_due(root: Path) -> dict:
    """整点或启动补查：daily（0:00～0:10）优先，否则 hourly；返回解析后的结果。"""
    proc = _run_manage(root, 'yecao_backup_scheduled', timeout=900)
    stdout = (proc.stdout or '').strip()
    stderr = (proc.stderr or '').strip()
    if stderr:
        _append_tray_log(root, '定时备份 stderr', stderr)
    if not stdout:
        return {'ok': proc.returncode == 0, 'skipped': True, 'message': '', 'health_ok': None}
    try:
        data = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError:
        return {
            'ok': proc.returncode == 0,
            'skipped': False,
            'message': stdout.splitlines()[-1] if stdout else '',
            'health_ok': None,
        }
    return data if isinstance(data, dict) else {}


def start_post_startup_backup_health_thread(
    root: Path,
    stop_event: threading.Event,
    *,
    icon=None,
    delay_sec: float = 5.0,
) -> threading.Thread:
    """启动成功后异步抽检最近备份；有异常再通知（不挡营业）。"""

    def _worker() -> None:
        if stop_event.wait(max(1.0, float(delay_sec))):
            return
        try:
            report = fetch_backup_health_report(root, limit=10)
        except (OSError, subprocess.TimeoutExpired):
            return
        if stop_event.is_set():
            return
        notify_backup_health_if_bad(report, via_icon=icon)

    thread = threading.Thread(target=_worker, daemon=True, name='yecao-backup-health')
    thread.start()
    return thread


def _seconds_until_next_local_hour() -> float:
    """睡到下一个本地整点（托盘进程内不依赖 Django）。"""
    now = datetime.now().astimezone()
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return max(1.0, (next_hour - now).total_seconds())


def start_scheduled_backup_thread(
    root: Path,
    stop_event: threading.Event,
    *,
    icon=None,
) -> threading.Thread:
    """后台睡到下一个整点再备份；启动后先补查一次 daily 窗口；日备抽检异常时通知。"""

    def _worker() -> None:
        try:
            result = run_scheduled_backup_if_due(root)
            if result.get('health_ok') is False:
                notify_backup_health_if_bad(
                    {
                        'all_ok': False,
                        'message': result.get('health_message') or result.get('message') or '',
                    },
                    via_icon=icon,
                )
        except (OSError, subprocess.TimeoutExpired):
            pass
        while not stop_event.is_set():
            wait_sec = _seconds_until_next_local_hour()
            if stop_event.wait(wait_sec):
                break
            try:
                result = run_scheduled_backup_if_due(root)
                if result.get('health_ok') is False:
                    notify_backup_health_if_bad(
                        {
                            'all_ok': False,
                            'message': result.get('health_message') or result.get('message') or '',
                        },
                        via_icon=icon,
                    )
            except (OSError, subprocess.TimeoutExpired):
                pass

    thread = threading.Thread(target=_worker, daemon=True, name='yecao-scheduled-backup')
    thread.start()
    return thread


# 兼容旧名
start_daily_backup_thread = start_scheduled_backup_thread
