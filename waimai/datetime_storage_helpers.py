# 库内时间存法：系统本地（USE_TZ=False）+ 旧 UTC 数据一次性换算

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any

from django.apps import apps
from django.conf import settings
from django.db import connections, models
from django.utils import timezone

from .time_helpers import format_local_iso, get_active_zoneinfo

STORAGE_MARKER_NAME = '.yecao_datetime_storage.json'
STORAGE_MODE_LOCAL = 'system_local'
STORAGE_MODE_LEGACY_UTC = 'legacy_utc_naive'
WORK_COPY_NAME = 'db.sqlite3.tzshift_work'


def storage_marker_path() -> Path:
    base = Path(getattr(settings, 'BASE_DIR', Path('.')))
    backup = base / 'backup'
    backup.mkdir(parents=True, exist_ok=True)
    return backup / STORAGE_MARKER_NAME


def load_storage_marker() -> dict[str, Any]:
    path = storage_marker_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_storage_marker(data: dict[str, Any]) -> None:
    path = storage_marker_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def datetime_storage_is_local() -> bool:
    return load_storage_marker().get('mode') == STORAGE_MODE_LOCAL


def utc_offset_hours_for_active_zone() -> int:
    """当前系统时区相对世界标准时的整点小时差（中日无夏令时，用固定参照日）。"""
    ref = datetime(2026, 1, 15, 12, 0, 0, tzinfo=dt_timezone.utc)
    local = ref.astimezone(get_active_zoneinfo())
    delta = local.utcoffset()
    if delta is None:
        return 0
    return int(delta.total_seconds() // 3600)


def utc_naive_to_local_naive(dt: datetime | None) -> datetime | None:
    """
    旧库（USE_TZ=True）写入的无时区数字 = 世界标准时墙钟。
    换成当前系统时区的墙钟数字（仍无时区，供 USE_TZ=False 存库）。
    """
    if dt is None:
        return None
    if timezone.is_aware(dt):
        local_aware = dt.astimezone(get_active_zoneinfo())
        return timezone.make_naive(local_aware, get_active_zoneinfo())
    aware_utc = timezone.make_aware(dt, dt_timezone.utc)
    local_aware = aware_utc.astimezone(get_active_zoneinfo())
    return timezone.make_naive(local_aware, get_active_zoneinfo())


def iter_datetime_model_fields():
    """遍历本库所有含 DateTimeField 的模型字段（含第三方 app）。"""
    for model in apps.get_models():
        for field in model._meta.local_fields:
            if isinstance(field, models.DateTimeField):
                yield model, field


def _shift_sqlite_file(db_path: Path, hours: int, columns: list[tuple[str, str, str]]) -> tuple[int, list[str]]:
    """对指定 sqlite 文件批量 +N hours。返回 (格数, 明细)。"""
    modifier = f'{hours:+d} hours'
    touched: list[str] = []
    updated_cells = 0
    conn = sqlite3.connect(str(db_path), timeout=120)
    try:
        conn.execute('PRAGMA busy_timeout=120000')
        for table, col, label in columns:
            try:
                count = conn.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" IS NOT NULL'
                ).fetchone()[0]
            except sqlite3.OperationalError:
                continue
            count = int(count or 0)
            if count <= 0:
                continue
            conn.execute(
                f'UPDATE "{table}" SET "{col}" = datetime("{col}", ?) WHERE "{col}" IS NOT NULL',
                (modifier,),
            )
            updated_cells += count
            touched.append(f'{label}:{count}')
        conn.commit()
    finally:
        conn.close()
    return updated_cells, touched


def live_sqlite_path() -> Path:
    """正式营业库路径（始终认项目根 db.sqlite3，不被 pending 工作副本绕开）。"""
    return Path(getattr(settings, 'BASE_DIR', Path('.'))) / 'db.sqlite3'


def purge_sqlite_sidecars(db_path: Path) -> None:
    """删除 -wal/-shm，避免盖回后旧日志把内容冲回去。"""
    for aux in (Path(str(db_path) + '-wal'), Path(str(db_path) + '-shm')):
        if not aux.exists():
            continue
        try:
            aux.unlink()
        except OSError:
            pass


def convert_all_utc_naive_datetimes_to_local(*, force: bool = False) -> dict[str, Any]:
    """
    一次性：把库内旧 UTC 墙钟数字改成系统本地墙钟。
    策略：先用 SQLite backup API 拷到工作副本再改，再尝试盖回正式库。
    """
    marker = load_storage_marker()
    if marker.get('mode') == STORAGE_MODE_LOCAL and not force:
        return {
            'ok': True,
            'skipped': True,
            'message': '已是系统本地存法，跳过转换（防止时间被连加两次）。',
            'updated_cells': 0,
        }

    hours = utc_offset_hours_for_active_zone()
    if hours == 0:
        new_marker = {
            'mode': STORAGE_MODE_LOCAL,
            'converted_from': STORAGE_MODE_LEGACY_UTC,
            'converted_at': format_local_iso(),
            'time_zone': getattr(settings, 'TIME_ZONE', ''),
            'offset_hours': 0,
            'updated_cells': 0,
            'touched': [],
            'note': '时区为 UTC，库内数字无需平移',
        }
        save_storage_marker(new_marker)
        return {
            'ok': True,
            'skipped': False,
            'message': '当前系统时区为 UTC，已标记为本地存法（数字未改）。',
            'updated_cells': 0,
            'touched': [],
            'marker': new_marker,
        }

    db_path = live_sqlite_path()
    if not db_path.is_file():
        return {
            'ok': False,
            'skipped': False,
            'message': f'找不到正式库：{db_path}',
            'updated_cells': 0,
        }

    work_path = db_path.with_name(WORK_COPY_NAME)
    columns = [
        (model._meta.db_table, field.column, f'{model._meta.label}.{field.name}')
        for model, field in iter_datetime_model_fields()
    ]
    modifier = f'{hours:+d} hours'

    connections.close_all()
    purge_sqlite_sidecars(db_path)

    # 1) 稳定拷贝到工作副本
    try:
        for p in (work_path, Path(str(work_path) + '-wal'), Path(str(work_path) + '-shm')):
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
        src = sqlite3.connect(f'file:{db_path.as_posix()}?mode=ro', uri=True, timeout=120)
        dst = sqlite3.connect(str(work_path), timeout=120)
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
            src.close()
    except (OSError, sqlite3.Error) as exc:
        return {
            'ok': False,
            'skipped': False,
            'message': f'无法制作转换工作副本：{exc}',
            'updated_cells': 0,
        }

    # 2) 只改工作副本
    try:
        updated_cells, touched = _shift_sqlite_file(work_path, hours, columns)
    except sqlite3.Error as exc:
        return {
            'ok': False,
            'skipped': False,
            'message': f'工作副本转换失败：{exc}',
            'updated_cells': 0,
        }

    # 3) 盖回正式库（先清附属文件，再改名替换；失败则保留工作副本）
    apply_result = _replace_live_with_work(db_path, work_path)
    applied = bool(apply_result.get('ok'))
    apply_error = apply_result.get('message') or ''

    new_marker = {
        'mode': STORAGE_MODE_LOCAL if applied else 'pending_apply',
        'converted_from': STORAGE_MODE_LEGACY_UTC,
        'converted_at': format_local_iso(),
        'time_zone': getattr(settings, 'TIME_ZONE', ''),
        'offset_hours': hours,
        'updated_cells': updated_cells,
        'touched': touched[:80],
        'applied': applied,
        'work_copy': str(work_path) if not applied else '',
        'apply_error': '' if applied else apply_error,
    }
    save_storage_marker(new_marker)

    if applied:
        return {
            'ok': True,
            'skipped': False,
            'message': f'已把旧世界标准时墙钟换成系统本地（{modifier}），共涉及 {updated_cells} 个时间格；正式库已盖回。',
            'updated_cells': updated_cells,
            'touched': touched,
            'marker': new_marker,
        }

    return {
        'ok': False,
        'skipped': False,
        'message': (
            f'工作副本已转换（{modifier}，{updated_cells} 格），但盖回正式库失败：{apply_error}。'
            f'请先停掉网页服务/托盘，再执行：python manage.py yecao_datetimes_utc_to_local --apply-work-copy'
        ),
        'updated_cells': updated_cells,
        'touched': touched,
        'marker': new_marker,
    }


def _replace_live_with_work(db_path: Path, work_path: Path) -> dict[str, Any]:
    """用已转换工作副本替换正式库；成功后删除工作副本及附属文件。"""
    connections.close_all()
    purge_sqlite_sidecars(db_path)
    purge_sqlite_sidecars(work_path)

    try:
        bak = db_path.with_name(db_path.name + '.pre_tzshift')
        if bak.exists():
            bak.unlink()
        if db_path.exists():
            os.replace(db_path, bak)
        os.replace(work_path, db_path)
        purge_sqlite_sidecars(db_path)
        # 工作副本附属一并清
        for p in (Path(str(work_path) + '-wal'), Path(str(work_path) + '-shm')):
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
        return {'ok': True, 'message': '改名盖回成功'}
    except OSError as exc_rename:
        # 改名失败：尝试原地 backup 覆盖，再强清 wal
        try:
            connections.close_all()
            purge_sqlite_sidecars(db_path)
            src = sqlite3.connect(str(work_path), timeout=60)
            dst = sqlite3.connect(str(db_path), timeout=60)
            try:
                dst.execute('PRAGMA busy_timeout=60000')
                src.backup(dst)
                dst.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                dst.commit()
            finally:
                dst.close()
                src.close()
            purge_sqlite_sidecars(db_path)
            try:
                work_path.unlink()
            except OSError:
                pass
            purge_sqlite_sidecars(work_path)
            return {'ok': True, 'message': f'改名失败后已原地覆盖（原错误：{exc_rename}）'}
        except (OSError, sqlite3.Error) as exc_backup:
            return {
                'ok': False,
                'message': f'改名失败：{exc_rename}；原地覆盖也失败：{exc_backup}',
            }


def apply_work_copy_to_live() -> dict[str, Any]:
    """把已转换的工作副本盖回正式库（须先停服务）。"""
    db_path = live_sqlite_path()
    work_path = db_path.with_name(WORK_COPY_NAME)
    if not work_path.is_file():
        return {'ok': False, 'message': f'找不到工作副本：{work_path}'}

    result = _replace_live_with_work(db_path, work_path)
    if not result.get('ok'):
        return {'ok': False, 'message': f"盖回失败：{result.get('message')}"}

    marker = load_storage_marker()
    marker['mode'] = STORAGE_MODE_LOCAL
    marker['applied'] = True
    marker['applied_at'] = format_local_iso()
    marker['work_copy'] = ''
    marker['apply_error'] = ''
    save_storage_marker(marker)
    return {'ok': True, 'message': '工作副本已盖回正式库，库内存法标记为系统本地。'}


def ensure_comparable(dt: datetime | None) -> datetime | None:
    """比较用：naive 视为系统本地并贴上时区，便于和带偏移的 ISO 互算。"""
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, get_active_zoneinfo())
    return dt
