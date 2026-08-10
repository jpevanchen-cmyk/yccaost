# 局域网主机放行：避免店内 IP 访问 400

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from waimai.v1_allowed_hosts_helpers import (
    apply_lan_url_to_allowed_hosts,
    hostname_from_http_base,
    merge_host_into_dotenv,
)


class HostnameFromLanTests(SimpleTestCase):
    def test_extracts_lan_host(self):
        self.assertEqual(
            hostname_from_http_base('http://192.168.3.120:8000'),
            '192.168.3.120',
        )

    def test_rejects_loopback(self):
        self.assertIsNone(hostname_from_http_base('http://127.0.0.1:8000'))
        self.assertIsNone(hostname_from_http_base('http://localhost:8000'))


class ApplyLanAllowedHostsTests(TestCase):
    def test_apply_adds_to_settings_without_touching_env(self):
        with override_settings(ALLOWED_HOSTS=['localhost', '127.0.0.1']):
            host = apply_lan_url_to_allowed_hosts(
                'http://192.168.1.88:8000',
                persist_env=False,
            )
            self.assertEqual(host, '192.168.1.88')
            self.assertIn('192.168.1.88', settings.ALLOWED_HOSTS)

    def test_merge_host_into_dotenv_file(self):
        tmp = Path(settings.BASE_DIR) / '.env_test_allowed_hosts'
        tmp.write_text('YECAO_ALLOWED_HOSTS=localhost,127.0.0.1\n', encoding='utf-8')
        try:
            self.assertTrue(merge_host_into_dotenv('192.168.1.88', env_path=tmp))
            text = tmp.read_text(encoding='utf-8')
            self.assertIn('192.168.1.88', text)
            self.assertIn('localhost', text)
        finally:
            tmp.unlink(missing_ok=True)
