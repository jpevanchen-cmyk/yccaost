# V1 SQLite WAL 数据保护

import sqlite3
import tempfile
from pathlib import Path

from django.db.backends.sqlite3.base import DatabaseWrapper
from django.test import SimpleTestCase, override_settings

from waimai.v1_sqlite_helpers import (
    apply_v1_sqlite_pragmas,
    read_sqlite_pragma_report,
    should_apply_v1_sqlite_pragmas,
    sqlite_database_name_is_file,
)


def _sqlite_wrapper(db_path: Path, *, alias: str = 'v1_sqlite_test') -> DatabaseWrapper:
    """独立 SQLite 连接（不依赖测试 runner 内存库）。"""
    settings_dict = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': db_path,
        'ATOMIC_REQUESTS': False,
        'AUTOCOMMIT': True,
        'CONN_MAX_AGE': 0,
        'CONN_HEALTH_CHECKS': False,
        'HOST': '',
        'PASSWORD': '',
        'PORT': '',
        'USER': '',
        'TIME_ZONE': None,
        'OPTIONS': {},
        'TEST': {},
    }
    wrapper = DatabaseWrapper(settings_dict, alias=alias)
    wrapper.ensure_connection()
    return wrapper


class V1SqliteNameTests(SimpleTestCase):
    def test_file_name_detection(self):
        self.assertFalse(sqlite_database_name_is_file(':memory:'))
        self.assertFalse(sqlite_database_name_is_file('file:memorydb?mode=memory&cache=shared'))
        self.assertTrue(sqlite_database_name_is_file('file:tmp.db?mode=ro'))
        self.assertTrue(sqlite_database_name_is_file(r'E:\YecaoST\db.sqlite3'))


class V1SqliteWalTests(SimpleTestCase):
    @override_settings(YECAO_V1_LOCAL_MODE=True)
    def test_wal_applied_on_v1_file_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / 'v1_wal_test.sqlite3'
            sqlite3.connect(str(db_path)).close()
            conn = _sqlite_wrapper(db_path)
            try:
                self.assertTrue(should_apply_v1_sqlite_pragmas(conn))
                values = apply_v1_sqlite_pragmas(conn)
                self.assertEqual(values.get('journal_mode'), 'wal')
                with conn.cursor() as cursor:
                    cursor.execute('PRAGMA journal_mode')
                    self.assertEqual(cursor.fetchone()[0].lower(), 'wal')
            finally:
                conn.close()

    @override_settings(YECAO_V1_LOCAL_MODE=False)
    def test_skips_when_not_v1(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / 'std_test.sqlite3'
            sqlite3.connect(str(db_path)).close()
            conn = _sqlite_wrapper(db_path)
            try:
                self.assertFalse(should_apply_v1_sqlite_pragmas(conn))
            finally:
                conn.close()

    @override_settings(YECAO_V1_LOCAL_MODE=True)
    def test_report_ok_on_v1_file_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / 'v1_report.sqlite3'
            sqlite3.connect(str(db_path)).close()
            conn = _sqlite_wrapper(db_path)
            try:
                report = read_sqlite_pragma_report(conn)
                self.assertTrue(report['should_apply'])
                self.assertTrue(report['ok'])
                self.assertEqual(str(report['pragmas'].get('journal_mode', '')).lower(), 'wal')
            finally:
                conn.close()

    @override_settings(YECAO_V1_LOCAL_MODE=True)
    def test_skips_memory_db_even_in_v1(self):
        conn = _sqlite_wrapper(Path(':memory:'))
        try:
            self.assertFalse(should_apply_v1_sqlite_pragmas(conn))
            report = read_sqlite_pragma_report(conn)
            self.assertFalse(report['should_apply'])
        finally:
            conn.close()

    @override_settings(YECAO_V1_LOCAL_MODE=True)
    def test_ensure_applies_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / 'v1_once.sqlite3'
            sqlite3.connect(str(db_path)).close()
            conn = _sqlite_wrapper(db_path)
            try:
                from waimai.v1_sqlite_helpers import ensure_v1_sqlite_pragmas

                ensure_v1_sqlite_pragmas(conn)
                ensure_v1_sqlite_pragmas(conn)
                with conn.cursor() as cursor:
                    cursor.execute('PRAGMA journal_mode')
                    self.assertEqual(cursor.fetchone()[0].lower(), 'wal')
            finally:
                conn.close()
