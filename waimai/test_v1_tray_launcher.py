# V1 托盘启动器：密码与管理命令

from django.test import TestCase

from launcher.tray_port_helpers import (
    command_line_is_yecao_runserver,
    foreign_listeners_on_port,
    format_port_busy_message,
)
from launcher.tray_password_helpers import (
    apply_tray_password_settings,
    clear_tray_password,
    exit_password_required,
    load_tray_password_settings,
    set_tray_password,
    startup_password_required,
    verify_tray_password,
)


class TrayPasswordHelpersTests(TestCase):
    def tearDown(self):
        clear_tray_password()

    def test_default_password_off(self):
        self.assertFalse(startup_password_required())
        self.assertFalse(exit_password_required())
        self.assertTrue(verify_tray_password('anything'))

    def test_set_and_verify(self):
        set_tray_password('TrayPass123', startup_enabled=True, exit_enabled=True)
        self.assertTrue(startup_password_required())
        self.assertTrue(exit_password_required())
        self.assertTrue(verify_tray_password('TrayPass123'))
        self.assertFalse(verify_tray_password('wrong'))

    def test_clear_password(self):
        set_tray_password('TrayPass123', startup_enabled=True, exit_enabled=False)
        clear_tray_password()
        settings = load_tray_password_settings()
        self.assertFalse(settings.get('password_hash'))

    def test_apply_uncheck_both_clears(self):
        from launcher.tray_password_helpers import password_is_configured

        set_tray_password('TrayPass123', startup_enabled=True, exit_enabled=True)
        ok, msg = apply_tray_password_settings(
            startup_enabled=False,
            exit_enabled=False,
            old_password='TrayPass123',
        )
        self.assertTrue(ok, msg)
        self.assertFalse(startup_password_required())
        self.assertFalse(password_is_configured())

    def test_apply_flags_only_keeps_password(self):
        set_tray_password('TrayPass123', startup_enabled=True, exit_enabled=True)
        ok, msg = apply_tray_password_settings(
            startup_enabled=True,
            exit_enabled=False,
            new_password='',
            old_password='TrayPass123',
        )
        self.assertTrue(ok, msg)
        self.assertTrue(startup_password_required())
        self.assertFalse(exit_password_required())
        self.assertTrue(verify_tray_password('TrayPass123'))


class LauncherConfigCommandTests(TestCase):
    def test_launcher_config_json(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command('yecao_launcher_config', stdout=out)
        import json

        data = json.loads(out.getvalue())
        self.assertIn('listen_port', data)
        self.assertIn('open_url', data)
        self.assertEqual(data['listen_port'], 8000)
        self.assertTrue(data['open_url'].startswith('http://127.0.0.1:'))

    def test_backup_on_exit_skipped_on_memory_db(self):
        from waimai.v1_backup_helpers import database_is_file_based

        if database_is_file_based():
            self.skipTest('开发机文件库可手工测 yecao_backup_on_exit')
        self.assertFalse(database_is_file_based())


class TrayPortHelpersTests(TestCase):
    def test_command_line_is_yecao_runserver(self):
        from launcher.tray_config_helpers import project_root

        root = project_root()
        manage = str((root / 'manage.py').resolve())
        self.assertTrue(
            command_line_is_yecao_runserver(
                f'python.exe {manage} runserver 0.0.0.0:8000 --noreload',
                root,
            )
        )
        self.assertFalse(command_line_is_yecao_runserver('python.exe other.py runserver', root))

    def test_format_port_busy_message(self):
        from launcher.tray_config_helpers import project_root
        from unittest.mock import patch

        with patch('launcher.tray_port_helpers.yecao_runserver_pids_on_port', return_value=[12345]):
            msg = format_port_busy_message(8000, [12345], project_root())
        self.assertIn('8000', msg)
        self.assertIn('12345', msg)

    def test_foreign_listeners_excludes_pid(self):
        from unittest.mock import patch

        with patch('launcher.tray_port_helpers.list_listening_pids', return_value=[1, 2, 3]):
            pids = foreign_listeners_on_port(8000, exclude_pids={2})
        self.assertEqual(pids, [1, 3])


class TrayServerStartGuardTests(TestCase):
    def test_start_blocked_when_port_busy(self):
        from launcher.tray_config_helpers import project_root
        from launcher.tray_server_helpers import TrayServerProcess
        from unittest.mock import patch

        server = TrayServerProcess(project_root())
        with patch(
            'launcher.tray_server_helpers.foreign_listeners_on_port',
            return_value=[4242],
        ), patch(
            'launcher.tray_server_helpers.fetch_launcher_config',
            return_value={'listen_port': 8000},
        ), patch(
            'launcher.tray_server_helpers.format_port_busy_message',
            return_value='端口 8000 已被占用，进程 4242',
        ):
            ok, msg = server.start()
        self.assertFalse(ok)
        self.assertIn('8000', msg)
        self.assertIn('4242', msg)
        self.assertFalse(server.running)
