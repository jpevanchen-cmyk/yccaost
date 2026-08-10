# 托盘端口清理：不杀当前自己的服务

from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from launcher.tray_port_helpers import describe_port_listeners, protect_pids_for_owned_server


class TrayPortProtectTests(TestCase):
    def test_describe_excludes_protected_yecao_pids(self):
        root = Path('.')
        with patch(
            'launcher.tray_port_helpers.list_listening_pids',
            return_value=[100, 200, 300],
        ), patch(
            'launcher.tray_port_helpers.yecao_runserver_pids_on_port',
            return_value=[100, 200],
        ):
            summary, killable = describe_port_listeners(
                8000, root, protect_pids={100},
            )
        self.assertEqual(killable, [200])
        self.assertIn('不会结束', summary)
        self.assertIn('100', summary)
        self.assertIn('可清理', summary)
        self.assertIn('200', summary)

    def test_only_own_service_no_kill_prompt_list(self):
        root = Path('.')
        with patch(
            'launcher.tray_port_helpers.list_listening_pids',
            return_value=[100],
        ), patch(
            'launcher.tray_port_helpers.yecao_runserver_pids_on_port',
            return_value=[100],
        ):
            summary, killable = describe_port_listeners(
                8000, root, protect_pids={100},
            )
        self.assertEqual(killable, [])
        self.assertIn('没有发现需要清理', summary)

    def test_protect_pids_includes_owned(self):
        with patch(
            'launcher.tray_port_helpers.list_direct_child_pids',
            return_value=[101],
        ):
            protect = protect_pids_for_owned_server(100)
        self.assertEqual(protect, {100, 101})
