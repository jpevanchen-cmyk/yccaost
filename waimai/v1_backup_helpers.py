# V1 本地营业：SQLite 稳定备份（重稳、不重快）

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import connections
from django.utils import timezone

from .time_helpers import format_local_iso, local_today, now_local_wall
from .v1_setup_helpers import default_backup_dir, normalize_backup_dir

META_FILENAME = '.yecao_backup_meta.json'
BACKUP_PREFIX = 'yecao_db_'
BACKUP_SUFFIX = '.sqlite3'
# 保留最近多少份备份（超出删最旧）
MAX_BACKUP_FILES = 90
# 抽检最近多少份备份是否完好（启动后 / 日备后）
BACKUP_HEALTH_CHECK_COUNT = 10
# 在线备份：每步复制页数；-1 表示一次复制全部（仍走官方 API，稳定）
BACKUP_PAGES_PER_STEP = -1
BACKUP_STEP_SLEEP = 0.0
# 打开源库最长等待（秒）
BACKUP_BUSY_TIMEOUT = 120.0
# SQLite 附属文件后缀（备份目录里只保留 .sqlite3 主文件）
SQLITE_AUX_SUFFIXES = ('-wal', '-shm', '-journal')


class V1BackupError(Exception):
    """备份/恢复失败（白话可展示）。"""


@dataclass
class BackupResult:
    ok: bool
    message: str
    backup_path: str = ''
    skipped: bool = False
    meta: dict[str, Any] | None = None
    # 日备后抽检（未抽检则为 None）
    health_ok: bool | None = None
    health_message: str = ''


@dataclass
class BackupHealthReport:
    """最近若干份备份的完整性抽检结果。"""

    checked: int = 0
    ok_count: int = 0
    bad_names: list[str] | None = None
    all_ok: bool = True
    message: str = ''
    backup_dir: str = ''

    def __post_init__(self) -> None:
        if self.bad_names is None:
            self.bad_names = []

    def as_dict(self) -> dict[str, Any]:
        return {
            'checked': self.checked,
            'ok_count': self.ok_count,
            'bad_names': list(self.bad_names or []),
            'all_ok': self.all_ok,
            'message': self.message,
            'backup_dir': self.backup_dir,
        }


def database_path() -> Path:
    db = settings.DATABASES.get('default', {})
    if db.get('ENGINE', '').endswith('sqlite3'):
        return Path(db['NAME'])
    raise V1BackupError('当前仅支持 SQLite 数据库备份。')


def database_is_file_based() -> bool:
    try:
        return database_path().is_file()
    except (TypeError, OSError, ValueError):
        return False


def resolve_backup_dir() -> Path:
    """
    解析自动备份目录。
    库损坏时禁止因读设置而崩：回落默认「项目/backup」。
    """
    try:
        from .owner_helpers import get_site_settings

        site = get_site_settings()
        raw = (site.v1_backup_dir or '').strip()
        if raw:
            return Path(normalize_backup_dir(raw))
    except Exception:
        # 库坏/未迁移等：仍须能找到默认备份目录做恢复
        pass
    return Path(default_backup_dir())


def user_facing_db_check_message(tech_detail: str = '') -> str:
    """把自检技术细节收成给用户看的短句。"""
    text = (tech_detail or '').strip().lower()
    if not text or text == 'ok':
        return ''
    if '不存在' in (tech_detail or '') or 'no such file' in text or 'does not exist' in text:
        return '营业数据文件不存在或打不开。'
    if (
        'not a database' in text
        or 'malformed' in text
        or 'disk image' in text
        or 'file is encrypted' in text
        or 'corrupt' in text
    ):
        return '营业数据文件已损坏，无法正常读取。'
    if 'traceback' in text or 'file "' in text or '.py"' in text:
        return '营业数据检查未通过。'
    # 短且非堆栈的原文可保留一句；过长则收口
    raw = (tech_detail or '').strip()
    if len(raw) <= 80 and '\n' not in raw and 'Traceback' not in raw:
        return f'营业数据检查未通过：{raw}'
    return '营业数据检查未通过。'


def meta_path(backup_dir: Path | None = None) -> Path:
    return (backup_dir or resolve_backup_dir()) / META_FILENAME


def load_backup_meta(backup_dir: Path | None = None) -> dict[str, Any]:
    path = meta_path(backup_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_backup_meta(meta: dict[str, Any], backup_dir: Path | None = None) -> None:
    directory = backup_dir or resolve_backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    meta_path(directory).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def integrity_check(db_path: Path | None = None) -> tuple[bool, str]:
    """对 SQLite 文件或当前 Django 连接做完整性检查。"""
    path = Path(db_path) if db_path is not None else database_path()
    if path.is_file():
        conn = None
        try:
            conn = sqlite3.connect(
                f'file:{path.as_posix()}?mode=ro',
                uri=True,
                timeout=BACKUP_BUSY_TIMEOUT,
            )
            row = conn.execute('PRAGMA integrity_check').fetchone()
            result = (row[0] if row else '').strip() or 'unknown'
            if result.lower() == 'ok':
                return True, 'ok'
            return False, result
        except sqlite3.Error as exc:
            return False, str(exc)
        finally:
            if conn is not None:
                conn.close()

    django_conn = _try_django_sqlite_connection()
    if django_conn is not None:
        try:
            row = django_conn.execute('PRAGMA integrity_check').fetchone()
            result = (row[0] if row else '').strip() or 'unknown'
            if result.lower() == 'ok':
                return True, 'ok'
            return False, result
        except sqlite3.Error as exc:
            return False, str(exc)
    return False, '数据库文件不存在'


def _database_uri_for_readonly() -> str | None:
    """构造 SQLite 只读 URI（与 Django 指向同一库，但不占用 Django 连接）。"""
    db_name = settings.DATABASES.get('default', {}).get('NAME')
    if db_name is None:
        return None
    name_str = str(db_name)
    if name_str.startswith('file:'):
        # 测试库 / 共享内存库：直接用原 URI，不再叠加 mode=ro
        if 'mode=memory' in name_str or 'mode=ro' in name_str:
            return name_str
        sep = '&' if '?' in name_str else '?'
        return f'{name_str}{sep}mode=ro'
    path = Path(name_str)
    if path.is_file():
        return f'file:{path.as_posix()}?mode=ro'
    return None


def _open_source_connection(source_path: Path | None) -> tuple[sqlite3.Connection, bool]:
    """
    打开备份源连接。
    若明确给了源文件路径，优先用该文件（测试/导出/指定路径）；
    否则再用当前营业库的只读 URI / Django 连接。
    返回 (连接, 是否由本函数创建并须在 finally 关闭)。
    """
    if source_path and Path(source_path).is_file():
        return _open_readonly_source(Path(source_path)), True
    uri = _database_uri_for_readonly()
    if uri:
        try:
            return sqlite3.connect(uri, uri=True, timeout=BACKUP_BUSY_TIMEOUT), True
        except sqlite3.Error:
            pass
    django_conn = _try_django_sqlite_connection()
    if django_conn is not None:
        return django_conn, False
    raise V1BackupError('找不到可备份的数据库')


def _open_readonly_source(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(
        f'file:{db_path.as_posix()}?mode=ro',
        uri=True,
        timeout=BACKUP_BUSY_TIMEOUT,
    )


def _sqlite_vendor(vendor: str) -> bool:
    return vendor in ('sqlite3', 'sqlite')


def _try_django_sqlite_connection() -> sqlite3.Connection | None:
    conn_wrapper = connections['default']
    if not _sqlite_vendor(conn_wrapper.vendor):
        return None
    try:
        conn_wrapper.ensure_connection()
        with conn_wrapper.cursor() as cursor:
            cursor.execute('SELECT 1')
        raw = conn_wrapper.connection
        if raw is not None:
            return raw
    except Exception:
        return None
    return None


def remove_sqlite_aux_files(db_path: Path) -> None:
    """删除某个库文件对应的 -wal / -shm / -journal 附属文件。"""
    base = str(Path(db_path))
    for suffix in SQLITE_AUX_SUFFIXES:
        aux = Path(base + suffix)
        if aux.is_file():
            try:
                aux.unlink()
            except OSError:
                pass


def cleanup_backup_directory(backup_dir: Path) -> None:
    """
    清理备份目录里不需要的附属/临时文件：
    · 主库名 + -wal / -shm / -journal
    · 含 .part 的临时库及其附属（如 xxx.sqlite3.part-wal）
    """
    if not backup_dir.is_dir():
        return
    for path in backup_dir.iterdir():
        if not path.is_file():
            continue
        name = path.name
        if name == META_FILENAME:
            continue
        if not name.startswith(BACKUP_PREFIX):
            continue
        # 正式备份只保留 *.sqlite3（不含 .part）
        if name.endswith(BACKUP_SUFFIX) and '.part' not in name:
            remove_sqlite_aux_files(path)
            continue
        # 其余 yecao_db_ 前缀的附属或临时文件一律删
        if any(name.endswith(suffix) for suffix in SQLITE_AUX_SUFFIXES):
            try:
                path.unlink()
            except OSError:
                pass
            continue
        if '.part' in name:
            try:
                path.unlink()
            except OSError:
                pass


def stable_sqlite_backup(source_path: Path | None, dest_path: Path) -> None:
    """
    用 SQLite 官方 online backup 复制库文件。
    分步复制 + 校验 + 原子替换，优先稳定。
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + '.part')
    if tmp_path.exists():
        tmp_path.unlink()
    remove_sqlite_aux_files(tmp_path)

    src, own_src = _open_source_connection(source_path)
    dst = sqlite3.connect(str(tmp_path))
    backup_error: V1BackupError | None = None
    try:
        # 官方 online backup：营业中也可安全复制
        src.backup(dst)
        dst.commit()
        # 尽量把 WAL 合并进主文件，减少落盘后的附属文件
        try:
            dst.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        except sqlite3.Error:
            pass
    except sqlite3.Error as exc:
        backup_error = V1BackupError(f'备份过程出错：{exc}')
    finally:
        dst.close()
        if own_src:
            src.close()

    remove_sqlite_aux_files(tmp_path)

    if backup_error is not None:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        remove_sqlite_aux_files(tmp_path)
        raise backup_error

    ok, msg = integrity_check(tmp_path)
    if not ok:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        remove_sqlite_aux_files(tmp_path)
        raise V1BackupError(f'备份文件校验未通过：{msg}')

    try:
        os.replace(tmp_path, dest_path)
    except OSError as exc:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        remove_sqlite_aux_files(tmp_path)
        raise V1BackupError(f'备份文件落盘失败：{exc}') from exc

    remove_sqlite_aux_files(tmp_path)
    remove_sqlite_aux_files(dest_path)
    cleanup_backup_directory(dest_path.parent)


def backup_filename(reason: str, moment: datetime | None = None) -> str:
    from .time_helpers import now_local_wall

    moment = moment or now_local_wall()
    if timezone.is_aware(moment):
        from .time_helpers import to_local

        moment = to_local(moment)
    stamp = moment.strftime('%Y%m%d_%H%M%S')
    safe_reason = ''.join(ch for ch in (reason or 'manual') if ch.isalnum() or ch in ('_', '-'))
    if not safe_reason:
        safe_reason = 'manual'
    return f'{BACKUP_PREFIX}{safe_reason}_{stamp}{BACKUP_SUFFIX}'


def rotate_old_backups(backup_dir: Path) -> None:
    files = sorted(
        backup_dir.glob(f'{BACKUP_PREFIX}*{BACKUP_SUFFIX}'),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in files[MAX_BACKUP_FILES:]:
        try:
            old.unlink()
        except OSError:
            pass
        remove_sqlite_aux_files(old)
    cleanup_backup_directory(backup_dir)


def find_latest_backup(backup_dir: Path | None = None) -> Path | None:
    files = list_recent_backups(backup_dir, limit=1)
    return files[0] if files else None


def list_recent_backups(
    backup_dir: Path | None = None,
    *,
    limit: int = BACKUP_HEALTH_CHECK_COUNT,
) -> list[Path]:
    """按修改时间从新到旧列出备份文件。"""
    directory = backup_dir or resolve_backup_dir()
    if not directory.is_dir():
        return []
    limit = max(1, int(limit or BACKUP_HEALTH_CHECK_COUNT))
    files = sorted(
        (
            p
            for p in directory.glob(f'{BACKUP_PREFIX}*{BACKUP_SUFFIX}')
            if p.is_file() and '.part' not in p.name
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[:limit]


def find_latest_healthy_backup(
    backup_dir: Path | None = None,
    *,
    scan_limit: int = BACKUP_HEALTH_CHECK_COUNT,
) -> Path | None:
    """从最近若干份里找第一份完整性检查通过的备份。"""
    for path in list_recent_backups(backup_dir, limit=scan_limit):
        ok, _ = integrity_check(path)
        if ok:
            return path
    return None


def inspect_recent_backups(
    *,
    limit: int = BACKUP_HEALTH_CHECK_COUNT,
    backup_dir: Path | None = None,
    save_meta: bool = True,
) -> BackupHealthReport:
    """
    抽检最近若干份备份是否完整可用。
    不删文件；结果可写入 meta，供托盘提示。
    """
    directory = backup_dir or resolve_backup_dir()
    files = list_recent_backups(directory, limit=limit)
    bad: list[str] = []
    ok_count = 0
    for path in files:
        ok, _detail = integrity_check(path)
        if ok:
            ok_count += 1
        else:
            bad.append(path.name)

    checked = len(files)
    all_ok = checked > 0 and not bad
    if checked == 0:
        message = '备份目录里还没有可抽检的备份文件。'
        all_ok = True  # 没有文件不算「备份损坏」，另由恢复流程处理
    elif not bad:
        message = f'已抽检最近 {checked} 份备份，全部完整可用。'
    else:
        preview = '、'.join(bad[:3])
        more = f' 等共 {len(bad)} 份' if len(bad) > 3 else f'（共 {len(bad)} 份）'
        message = (
            f'最近 {checked} 份备份中有 {len(bad)} 份打不开或不完整：{preview}{more}。'
            f'请尽快用托盘「立刻备份到所选文件夹」另存一份到 U 盘或其它盘。'
        )

    report = BackupHealthReport(
        checked=checked,
        ok_count=ok_count,
        bad_names=bad,
        all_ok=all_ok if checked > 0 else True,
        message=message,
        backup_dir=str(directory),
    )

    if save_meta:
        try:
            meta = load_backup_meta(directory)
            meta['last_health_check_at'] = format_local_iso()
            meta['last_health_checked'] = checked
            meta['last_health_ok_count'] = ok_count
            meta['last_health_bad_names'] = bad
            meta['last_health_all_ok'] = report.all_ok
            save_backup_meta(meta, directory)
        except OSError:
            pass

    return report


def run_backup(reason: str = 'manual', *, force: bool = False) -> BackupResult:
    """执行一次备份；daily 同一天默认跳过（除非 force）。"""
    reason = (reason or 'manual').strip().lower()
    backup_dir = resolve_backup_dir()
    meta = load_backup_meta(backup_dir)
    today = local_today().isoformat()

    if reason == 'daily' and not force:
        if meta.get('last_daily_backup_date') == today:
            return BackupResult(
                ok=True,
                message='今日定时备份已完成，跳过。',
                skipped=True,
                meta=meta,
            )

    if reason == 'hourly' and not force:
        if not should_run_hourly_backup_now(meta):
            return BackupResult(
                ok=True,
                message='距上次营业中备份不足 1 小时，跳过。',
                skipped=True,
                meta=meta,
            )

    db_path = database_path()
    filename = backup_filename(reason)
    dest = backup_dir / filename

    try:
        stable_sqlite_backup(db_path if db_path.is_file() else None, dest)
    except V1BackupError as exc:
        return BackupResult(ok=False, message=str(exc), meta=meta)

    from .time_helpers import format_local_iso

    now_iso = format_local_iso()
    meta.update(
        {
            'last_backup_at': now_iso,
            'last_backup_file': filename,
            'last_backup_reason': reason,
        },
    )
    if reason == 'daily':
        meta['last_daily_backup_date'] = today
    if reason == 'hourly':
        meta['last_hourly_backup_at'] = now_iso
    if reason == 'exit':
        meta['last_clean_exit_at'] = now_iso
        meta['last_clean_exit_backup'] = filename
        meta['clean_shutdown'] = True
    save_backup_meta(meta, backup_dir)
    rotate_old_backups(backup_dir)

    return BackupResult(
        ok=True,
        message=f'备份成功：{dest}',
        backup_path=str(dest),
        meta=meta,
    )


def run_backup_to_directory(dest_dir: str | Path, *, reason: str = 'export') -> BackupResult:
    """
    立刻备份到用户所选文件夹。
    不写入默认自动备份目录的轮转；仅在默认备份 meta 记一笔「上次导出」。
    """
    from .time_helpers import format_local_iso

    raw = str(dest_dir or '').strip()
    if not raw:
        return BackupResult(ok=False, message='请先选择要存放备份的文件夹。')
    try:
        directory = Path(normalize_backup_dir(raw))
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return BackupResult(ok=False, message=f'无法使用所选文件夹：{exc}')

    if not directory.is_dir():
        return BackupResult(ok=False, message='所选路径不是可用的文件夹。')

    db_path = database_path()
    filename = backup_filename(reason or 'export')
    dest = directory / filename
    try:
        stable_sqlite_backup(db_path if db_path.is_file() else None, dest)
    except V1BackupError as exc:
        return BackupResult(ok=False, message=str(exc))

    # 记录到默认备份目录的 meta（方便排查）；不在所选文件夹做 90 份轮转
    official_dir = resolve_backup_dir()
    meta = load_backup_meta(official_dir)
    now_iso = format_local_iso()
    meta['last_export_at'] = now_iso
    meta['last_export_file'] = str(dest)
    meta['last_backup_at'] = now_iso
    meta['last_backup_file'] = filename
    meta['last_backup_reason'] = (reason or 'export').strip().lower() or 'export'
    try:
        official_dir.mkdir(parents=True, exist_ok=True)
        save_backup_meta(meta, official_dir)
    except OSError:
        # 导出文件已成功；meta 写失败不阻断
        pass

    return BackupResult(
        ok=True,
        message=f'已备份到：{dest}',
        backup_path=str(dest),
        meta=meta,
    )


def mark_startup_seen() -> None:
    """托盘已启动：标记本次运行开始（退出并成功备份后才算 clean）。"""
    from .time_helpers import format_local_iso

    backup_dir = resolve_backup_dir()
    meta = load_backup_meta(backup_dir)
    meta['last_startup_at'] = format_local_iso()
    meta['clean_shutdown'] = False
    save_backup_meta(meta, backup_dir)


def startup_database_report() -> dict[str, Any]:
    """启动前检查：完整性 + 是否疑似异常退出 + 最近备份。坏库时也必须能回报最近备份。"""
    import logging
    import traceback

    logger = logging.getLogger('waimai')
    db_path = database_path()
    tech_parts: list[str] = []
    try:
        backup_dir = resolve_backup_dir()
    except Exception as exc:
        tech_parts.append(f'resolve_backup_dir: {exc}')
        backup_dir = Path(default_backup_dir())

    meta: dict[str, Any] = {}
    try:
        meta = load_backup_meta(backup_dir)
    except Exception as exc:
        tech_parts.append(f'load_backup_meta: {exc}')

    try:
        ok, detail = integrity_check(db_path)
    except Exception as exc:
        ok = False
        detail = str(exc)
        tech_parts.append(traceback.format_exc())
        logger.exception('启动自检 integrity_check 异常')

    latest = ''
    try:
        latest_path = find_latest_healthy_backup(
            backup_dir, scan_limit=BACKUP_HEALTH_CHECK_COUNT,
        )
        if latest_path is None:
            latest_path = find_latest_backup(backup_dir)
        latest = str(latest_path) if latest_path else ''
    except Exception as exc:
        tech_parts.append(f'find_latest_backup: {exc}')

    if not ok:
        tech_parts.insert(0, detail or '')
    tech_detail = '\n'.join(p for p in tech_parts if p).strip()
    user_detail = user_facing_db_check_message(detail if not ok else '') or (
        '' if ok else '营业数据检查未通过。'
    )

    abnormal = (
        meta.get('clean_shutdown') is False
        and bool(meta.get('last_startup_at'))
        and bool(meta.get('last_backup_at'))
    )
    return {
        'ok': ok,
        'detail': user_detail if not ok else (detail or 'ok'),
        'tech_detail': tech_detail if not ok else '',
        'user_message': user_detail,
        'database': str(db_path),
        'backup_dir': str(backup_dir),
        'latest_backup': latest,
        'abnormal_shutdown_suspected': abnormal,
        'meta': meta,
    }


def restore_latest_backup(*, keep_corrupt_copy: bool = True) -> BackupResult:
    """用最近一份完好备份覆盖当前库（须先停网页服务）。"""
    backup_dir = resolve_backup_dir()
    latest = find_latest_healthy_backup(backup_dir, scan_limit=BACKUP_HEALTH_CHECK_COUNT)
    if not latest:
        # 再看有没有文件但全坏
        any_file = find_latest_backup(backup_dir)
        if any_file:
            return BackupResult(
                ok=False,
                message=(
                    f'最近 {BACKUP_HEALTH_CHECK_COUNT} 份备份均不完整或打不开，无法自动恢复。'
                    '请维护者指定一份完好备份文件恢复。'
                ),
            )
        return BackupResult(ok=False, message='备份目录里没有可恢复的副本。')
    return restore_from_backup(latest, keep_corrupt_copy=keep_corrupt_copy)


def restore_from_backup(backup_file: Path, *, keep_corrupt_copy: bool = True) -> BackupResult:
    backup_file = Path(backup_file)
    if not backup_file.is_file():
        return BackupResult(ok=False, message='指定的备份文件不存在。')

    ok, msg = integrity_check(backup_file)
    if not ok:
        return BackupResult(ok=False, message=f'备份文件已损坏，无法恢复：{msg}')

    db_path = database_path()
    if not database_is_file_based():
        return BackupResult(
            ok=False,
            message='当前数据库不在磁盘文件中，无法执行文件恢复（请使用正式安装的 SQLite 库文件）。',
        )
    connections.close_all()

    if db_path.is_file() and keep_corrupt_copy:
        from .time_helpers import now_local_wall

        corrupt_name = db_path.with_name(
            db_path.name + f'.corrupt_{now_local_wall().strftime("%Y%m%d_%H%M%S")}',
        )
        try:
            os.replace(db_path, corrupt_name)
        except OSError as exc:
            return BackupResult(ok=False, message=f'无法保留当前数据库：{exc}')

    tmp_target = db_path.with_suffix(db_path.suffix + '.restore.part')
    restore_error: str | None = None
    try:
        # 恢复也走 backup API：从只读备份拷到目标，避免半写
        src = _open_readonly_source(backup_file)
        dst = sqlite3.connect(str(tmp_target))
        try:
            src.backup(dst, pages=BACKUP_PAGES_PER_STEP, sleep=BACKUP_STEP_SLEEP)
            dst.commit()
        finally:
            dst.close()
            src.close()
    except sqlite3.Error as exc:
        restore_error = f'恢复过程出错：{exc}'

    if restore_error:
        if tmp_target.exists():
            try:
                tmp_target.unlink()
            except OSError:
                pass
        return BackupResult(ok=False, message=restore_error)

    ok, check_msg = integrity_check(tmp_target)
    if not ok:
        if tmp_target.exists():
            try:
                tmp_target.unlink()
            except OSError:
                pass
        return BackupResult(ok=False, message=f'恢复后校验失败：{check_msg}')

    try:
        os.replace(tmp_target, db_path)
    except OSError as exc:
        if tmp_target.exists():
            try:
                tmp_target.unlink()
            except OSError:
                pass
        remove_sqlite_aux_files(tmp_target)
        return BackupResult(ok=False, message=f'恢复落盘失败：{exc}')

    remove_sqlite_aux_files(tmp_target)
    remove_sqlite_aux_files(db_path)

    directory = resolve_backup_dir()
    meta = load_backup_meta(directory)
    from .time_helpers import format_local_iso

    meta['last_restore_at'] = format_local_iso()
    meta['last_restore_from'] = backup_file.name
    meta['clean_shutdown'] = True
    save_backup_meta(meta, directory)

    return BackupResult(
        ok=True,
        message=f'已从备份恢复：{backup_file.name}',
        backup_path=str(backup_file),
        meta=meta,
    )


def write_cli_message(stdout, style, message: str, *, ok: bool = True) -> None:
    """写管理命令输出；Windows 控制台编码不对时用英文兜底，避免备份已成功却报 exit 1。"""
    try:
        stdout.write(style(message))
    except UnicodeEncodeError:
        fallback = 'backup ok' if ok else 'backup failed'
        stdout.write(style(fallback))


def should_run_daily_backup_now() -> bool:
    """本地时间 0:00～0:10 且今日尚未 daily 备份。"""
    from .time_helpers import now_local_wall

    now = now_local_wall()
    if now.hour != 0 or now.minute > 10:
        return False
    meta = load_backup_meta()
    return meta.get('last_daily_backup_date') != now.date().isoformat()


def _parse_meta_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    from .datetime_storage_helpers import ensure_comparable

    dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
    return ensure_comparable(dt)


def should_run_hourly_backup_now(meta: dict[str, Any] | None = None) -> bool:
    """距上次 hourly 全量备份已满 1 小时（或从未备过）。"""
    from .datetime_storage_helpers import ensure_comparable

    meta = meta if meta is not None else load_backup_meta()
    last = _parse_meta_datetime(meta.get('last_hourly_backup_at'))
    if last is None:
        return True
    last_c = ensure_comparable(last)
    now_c = ensure_comparable(now_local_wall())
    return now_c - last_c >= timedelta(hours=1)


def run_scheduled_backup(*, force: bool = False) -> BackupResult:
    """
    托盘整点调用：优先 0 点 daily，否则营业中 hourly（满 1 小时才执行）。
    日备成功完成后，再抽检最近 10 份备份是否完整可用。
    """
    if should_run_daily_backup_now():
        result = run_backup('daily', force=force)
        if result.ok and not result.skipped:
            health = inspect_recent_backups(limit=BACKUP_HEALTH_CHECK_COUNT)
            result.health_ok = health.all_ok
            result.health_message = health.message
            if not health.all_ok:
                result.message = f'{result.message}；抽检：{health.message}'
            else:
                result.message = (
                    f'{result.message}；已抽检最近 {health.checked} 份备份，全部可用。'
                )
        return result
    if should_run_hourly_backup_now():
        return run_backup('hourly', force=force)
    return BackupResult(
        ok=True,
        message='未到定时备份时间，跳过。',
        skipped=True,
    )


def seconds_until_next_local_hour() -> float:
    """距离下一个本地整点的秒数（至少 1 秒）。"""
    from .time_helpers import now_local_wall

    now = now_local_wall()
    nxt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return max(1.0, (nxt - now).total_seconds())
