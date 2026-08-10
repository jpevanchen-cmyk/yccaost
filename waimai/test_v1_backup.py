# V1 稳定备份

import sqlite3
import tempfile
from pathlib import Path

from django.test import SimpleTestCase
from .time_helpers import now_local_wall

from waimai.v1_backup_helpers import (
    cleanup_backup_directory,
    integrity_check,
    stable_sqlite_backup,
    user_facing_db_check_message,
)


def _make_source_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS backup_test (id INTEGER PRIMARY KEY)')
        conn.execute('INSERT INTO backup_test (id) VALUES (1)')
        conn.commit()
    finally:
        conn.close()


class V1BackupHelperTests(SimpleTestCase):
    def test_stable_backup_file_to_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'src.sqlite3'
            dest = Path(tmp) / 'dest.sqlite3'
            _make_source_db(src)
            stable_sqlite_backup(src, dest)
            self.assertTrue(dest.is_file())
            names = {p.name for p in Path(tmp).iterdir() if p.is_file()}
            self.assertIn('dest.sqlite3', names)
            self.assertFalse(any('.part' in n or n.endswith('-wal') or n.endswith('-shm') for n in names))
            ok, msg = integrity_check(dest)
            self.assertTrue(ok, msg)

    def test_stable_backup_cleans_orphan_aux_in_backup_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp)
            src = backup_dir / 'live.sqlite3'
            dest = backup_dir / 'yecao_db_hourly_20260808_120000.sqlite3'
            _make_source_db(src)
            # 模拟旧逻辑留下的附属文件
            (backup_dir / 'yecao_db_daily_20260808_091420.sqlite3.part-wal').write_bytes(b'x')
            (backup_dir / 'yecao_db_daily_20260808_091420.sqlite3.part-shm').write_bytes(b'x')
            stable_sqlite_backup(src, dest)
            names = {p.name for p in backup_dir.iterdir() if p.is_file()}
            self.assertIn('yecao_db_hourly_20260808_120000.sqlite3', names)
            self.assertFalse(any('.part' in n or n.endswith('-wal') or n.endswith('-shm') for n in names))

    def test_cleanup_backup_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp)
            (backup_dir / 'yecao_db_test_20260101.sqlite3').write_bytes(b'')
            (backup_dir / 'yecao_db_test_20260101.sqlite3-wal').write_bytes(b'')
            (backup_dir / 'yecao_db_old.sqlite3.part-wal').write_bytes(b'')
            cleanup_backup_directory(backup_dir)
            names = {p.name for p in backup_dir.iterdir() if p.is_file()}
            self.assertEqual(names, {'yecao_db_test_20260101.sqlite3'})

    def test_integrity_rejects_missing(self):
        ok, msg = integrity_check(Path('Z:/no/such/yecao_test_db.sqlite3'))
        self.assertFalse(ok)

    def test_backup_filename_and_meta_helpers(self):
        from waimai.v1_backup_helpers import backup_filename, load_backup_meta, save_backup_meta

        name = backup_filename('exit')
        self.assertTrue(name.startswith('yecao_db_exit_'))
        name_hourly = backup_filename('hourly')
        self.assertIn('hourly', name_hourly)
        with tempfile.TemporaryDirectory() as tmp:
            meta = {'hello': 'world'}
            save_backup_meta(meta, Path(tmp))
            loaded = load_backup_meta(Path(tmp))
            self.assertEqual(loaded.get('hello'), 'world')


class V1ScheduledBackupTests(SimpleTestCase):
    def test_should_run_hourly_when_never_backed_up(self):
        from waimai.v1_backup_helpers import should_run_hourly_backup_now

        self.assertTrue(should_run_hourly_backup_now({}))

    def test_should_skip_hourly_within_one_hour(self):
        from django.utils import timezone
        from waimai.v1_backup_helpers import should_run_hourly_backup_now

        meta = {'last_hourly_backup_at': now_local_wall().isoformat()}
        self.assertFalse(should_run_hourly_backup_now(meta))

    def test_run_scheduled_prefers_daily_in_window(self):
        from unittest.mock import patch

        from waimai.v1_backup_helpers import BackupResult, run_scheduled_backup

        with patch('waimai.v1_backup_helpers.should_run_daily_backup_now', return_value=True), patch(
            'waimai.v1_backup_helpers.run_backup',
            return_value=BackupResult(ok=True, message='daily ok'),
        ) as mock_run:
            result = run_scheduled_backup()
        mock_run.assert_called_once_with('daily', force=False)
        self.assertTrue(result.ok)

    def test_run_scheduled_hourly_when_not_daily_window(self):
        from unittest.mock import patch

        from waimai.v1_backup_helpers import BackupResult, run_scheduled_backup

        with patch('waimai.v1_backup_helpers.should_run_daily_backup_now', return_value=False), patch(
            'waimai.v1_backup_helpers.should_run_hourly_backup_now',
            return_value=True,
        ), patch(
            'waimai.v1_backup_helpers.run_backup',
            return_value=BackupResult(ok=True, message='hourly ok'),
        ) as mock_run:
            result = run_scheduled_backup()
        mock_run.assert_called_once_with('hourly', force=False)
        self.assertTrue(result.ok)


class V1ExportBackupTests(SimpleTestCase):
    def test_run_backup_to_directory_writes_file(self):
        from unittest.mock import patch

        from waimai.v1_backup_helpers import run_backup_to_directory

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'live.sqlite3'
            export_dir = Path(tmp) / 'usb'
            export_dir.mkdir()
            _make_source_db(src)
            with patch('waimai.v1_backup_helpers.database_path', return_value=src), patch(
                'waimai.v1_backup_helpers.resolve_backup_dir',
                return_value=Path(tmp) / 'official_backup',
            ):
                (Path(tmp) / 'official_backup').mkdir()
                result = run_backup_to_directory(export_dir, reason='export')
            self.assertTrue(result.ok, result.message)
            self.assertTrue(Path(result.backup_path).is_file())
            self.assertTrue(Path(result.backup_path).name.startswith('yecao_db_export_'))
            ok, msg = integrity_check(Path(result.backup_path))
            self.assertTrue(ok, msg)

    def test_run_backup_to_directory_requires_path(self):
        from waimai.v1_backup_helpers import run_backup_to_directory

        result = run_backup_to_directory('   ')
        self.assertFalse(result.ok)


class V1StartupCheckPlainMessageTests(SimpleTestCase):
    def test_user_facing_maps_not_a_database(self):
        msg = user_facing_db_check_message('file is not a database')
        self.assertIn('损坏', msg)
        self.assertNotIn('Traceback', msg)

    def test_startup_report_finds_backup_when_db_corrupt(self):
        from unittest.mock import patch

        from waimai.v1_backup_helpers import startup_database_report

        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'db.sqlite3'
            bad.write_text('not-a-db', encoding='utf-8')
            backup_dir = Path(tmp) / 'backup'
            backup_dir.mkdir()
            good = backup_dir / 'yecao_db_manual_20260809_120000.sqlite3'
            _make_source_db(good)
            with patch('waimai.v1_backup_helpers.database_path', return_value=bad), patch(
                'waimai.v1_backup_helpers.resolve_backup_dir',
                return_value=backup_dir,
            ):
                report = startup_database_report()
            self.assertFalse(report['ok'])
            self.assertTrue(report['latest_backup'])
            self.assertIn('损坏', report['detail'])
            self.assertNotIn('Traceback', report['detail'])
            self.assertIn('not a database', (report.get('tech_detail') or '').lower())


class V1BackupHealthInspectTests(SimpleTestCase):
    def test_inspect_reports_bad_among_recent(self):
        from waimai.v1_backup_helpers import inspect_recent_backups

        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp)
            good = backup_dir / 'yecao_db_manual_20260809_120000.sqlite3'
            bad = backup_dir / 'yecao_db_manual_20260809_130000.sqlite3'
            _make_source_db(good)
            bad.write_bytes(b'not-a-database')
            report = inspect_recent_backups(
                limit=10, backup_dir=backup_dir, save_meta=False,
            )
            self.assertEqual(report.checked, 2)
            self.assertFalse(report.all_ok)
            self.assertIn(bad.name, report.bad_names or [])
            self.assertIn('打不开', report.message)

    def test_find_latest_healthy_skips_corrupt(self):
        from waimai.v1_backup_helpers import find_latest_healthy_backup

        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp)
            older_good = backup_dir / 'yecao_db_manual_20260809_110000.sqlite3'
            newer_bad = backup_dir / 'yecao_db_manual_20260809_120000.sqlite3'
            _make_source_db(older_good)
            newer_bad.write_bytes(b'junk')
            # 新文件更晚改时间
            newer_bad.touch()
            found = find_latest_healthy_backup(backup_dir, scan_limit=10)
            self.assertEqual(found, older_good)

    def test_run_scheduled_daily_attaches_health(self):
        from unittest.mock import patch

        from waimai.v1_backup_helpers import BackupResult, run_scheduled_backup

        daily = BackupResult(ok=True, message='daily ok', skipped=False)
        health_msg = '已抽检最近 1 份备份，全部完整可用。'

        class _H:
            all_ok = True
            message = health_msg
            checked = 1

        with patch('waimai.v1_backup_helpers.should_run_daily_backup_now', return_value=True), patch(
            'waimai.v1_backup_helpers.run_backup',
            return_value=daily,
        ), patch(
            'waimai.v1_backup_helpers.inspect_recent_backups',
            return_value=_H(),
        ):
            result = run_scheduled_backup()
        self.assertTrue(result.ok)
        self.assertTrue(result.health_ok)
        self.assertIn('抽检', result.message)
