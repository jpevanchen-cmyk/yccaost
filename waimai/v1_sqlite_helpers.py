# V1 本地营业：SQLite 数据保护（WAL + 忙等，仅 V1 文件库）

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from django.db.backends.base.base import BaseDatabaseWrapper

from .v1_local_helpers import v1_local_mode_enabled

logger = logging.getLogger(__name__)

# 与备份模块一致：写库冲突时最长等待（毫秒）
BUSY_TIMEOUT_MS = 120_000


def _sqlite_vendor(vendor: str) -> bool:
    return vendor in ('sqlite3', 'sqlite')


def sqlite_database_name_is_file(name: object) -> bool:
    """是否为磁盘上的 SQLite 文件（排除内存库与测试 shared memory）。"""
    if name is None:
        return False
    text = str(name)
    if text == ':memory:':
        return False
    if text.startswith('file:'):
        return 'mode=memory' not in text
    return True


def should_apply_v1_sqlite_pragmas(connection: BaseDatabaseWrapper) -> bool:
    """仅 V1 模式 + SQLite 文件库时启用 WAL 等保护。"""
    if not v1_local_mode_enabled():
        return False
    if not _sqlite_vendor(getattr(connection, 'vendor', '')):
        return False
    return sqlite_database_name_is_file(connection.settings_dict.get('NAME'))


def apply_v1_sqlite_pragmas(connection: BaseDatabaseWrapper) -> dict[str, str]:
    """
    开启 WAL 与相关 PRAGMA（幂等：已是 WAL 则不会降级）。
    返回各 PRAGMA 读回值，供自检命令使用。
    """
    results: dict[str, str] = {}
    with connection.cursor() as cursor:
        cursor.execute('PRAGMA journal_mode=WAL')
        row = cursor.fetchone()
        results['journal_mode'] = (row[0] if row else '').strip().lower()

        cursor.execute(f'PRAGMA busy_timeout={int(BUSY_TIMEOUT_MS)}')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.execute('PRAGMA foreign_keys=ON')

        cursor.execute('PRAGMA busy_timeout')
        row = cursor.fetchone()
        results['busy_timeout'] = str(row[0] if row else '')

        cursor.execute('PRAGMA synchronous')
        row = cursor.fetchone()
        results['synchronous'] = str(row[0] if row else '').strip().upper()

        cursor.execute('PRAGMA foreign_keys')
        row = cursor.fetchone()
        results['foreign_keys'] = str(row[0] if row else '')

    if results.get('journal_mode') != 'wal':
        logger.warning('V1 SQLite 未能切换到 WAL，当前 journal_mode=%s', results.get('journal_mode'))
    return results


def ensure_v1_sqlite_pragmas(connection: BaseDatabaseWrapper) -> dict[str, str] | None:
    """若适用则应用 PRAGMA；同一连接只执行一次。"""
    if getattr(connection, '_v1_sqlite_pragmas_applied', False):
        return getattr(connection, '_v1_sqlite_pragma_values', None)
    if not should_apply_v1_sqlite_pragmas(connection):
        return None
    values = apply_v1_sqlite_pragmas(connection)
    connection._v1_sqlite_pragmas_applied = True  # type: ignore[attr-defined]
    connection._v1_sqlite_pragma_values = values  # type: ignore[attr-defined]
    return values


def on_connection_created(sender, connection: BaseDatabaseWrapper, **kwargs) -> None:
    """Django 建连后自动为 V1 文件库启用 WAL。"""
    ensure_v1_sqlite_pragmas(connection)


def read_sqlite_pragma_report(connection: BaseDatabaseWrapper | None = None) -> dict[str, Any]:
    """读取当前连接的 SQLite 保护项（JSON 自检用）。"""
    from django.db import connections

    conn = connection or connections['default']
    conn.ensure_connection()

    name = conn.settings_dict.get('NAME')
    report: dict[str, Any] = {
        'v1_mode': v1_local_mode_enabled(),
        'vendor': conn.vendor,
        'database': str(name) if name is not None else '',
        'file_database': sqlite_database_name_is_file(name),
        'should_apply': should_apply_v1_sqlite_pragmas(conn),
        'ok': True,
        'detail': 'ok',
        'pragmas': {},
    }

    if not _sqlite_vendor(conn.vendor):
        report['ok'] = True
        report['detail'] = '非 SQLite，跳过'
        return report

    if not report['should_apply']:
        report['detail'] = '非 V1 或内存库，未启用 WAL'
        return report

    ensure_v1_sqlite_pragmas(conn)
    with conn.cursor() as cursor:
        for key, sql in (
            ('journal_mode', 'PRAGMA journal_mode'),
            ('busy_timeout', 'PRAGMA busy_timeout'),
            ('synchronous', 'PRAGMA synchronous'),
            ('foreign_keys', 'PRAGMA foreign_keys'),
        ):
            cursor.execute(sql)
            row = cursor.fetchone()
            report['pragmas'][key] = row[0] if row else ''

    journal = str(report['pragmas'].get('journal_mode', '')).lower()
    if journal != 'wal':
        report['ok'] = False
        report['detail'] = f'journal_mode 应为 wal，当前为 {journal or "未知"}'
    return report
