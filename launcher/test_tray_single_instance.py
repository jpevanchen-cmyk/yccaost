# 托盘同安装目录单实例

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from launcher.tray_single_instance_helpers import (
    consume_show_window_request,
    mutex_name_for_install,
    request_show_existing_window,
    show_window_flag_path,
)


class TraySingleInstanceHelpersTests(TestCase):
    def test_mutex_name_stable_per_path(self):
        a = mutex_name_for_install(Path('C:/YecaoST'))
        b = mutex_name_for_install(Path('C:/YecaoST'))
        c = mutex_name_for_install(Path('C:/Other'))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertTrue(a.startswith('Local\\YecaoST_Tray_'))

    def test_show_window_flag_roundtrip(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(consume_show_window_request(root))
            request_show_existing_window(root)
            self.assertTrue(show_window_flag_path(root).is_file())
            self.assertTrue(consume_show_window_request(root))
            self.assertFalse(show_window_flag_path(root).is_file())
            self.assertFalse(consume_show_window_request(root))
