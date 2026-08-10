# V1 首次向导 7 步

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from waimai.models import ShopProfile
from waimai.operating_helpers import get_operating_settings
from waimai.owner_helpers import get_site_settings
from waimai.plugin_runtime.registry import is_plugin_enabled
from waimai.test_shop_helpers import create_test_shop_bundle
from waimai.v1_local_helpers import INSTALL_MODE_V1_LOCAL, v1_local_mode_enabled
from waimai.v1_setup_helpers import (
    V1_SETUP_SESSION_SECONDS,
    any_v1_shop_exists,
    should_auto_redirect_to_v1_setup,
    v1_setup_completed,
)
from waimai.v1_setup_forms import V1SetupBackupForm, V1SetupNetworkForm


class V1SetupHelpersTests(TestCase):
    def test_default_no_auto_redirect(self):
        self.assertFalse(should_auto_redirect_to_v1_setup())

    @override_settings(YECAO_V1_INSTALL_PENDING=True)
    def test_pending_empty_db_redirects(self):
        self.assertTrue(should_auto_redirect_to_v1_setup())

    @override_settings(YECAO_V1_INSTALL_PENDING=True)
    def test_pending_with_existing_shop_no_redirect(self):
        create_test_shop_bundle(username='existing_v1_shop')
        self.assertFalse(should_auto_redirect_to_v1_setup())
        self.assertTrue(any_v1_shop_exists())


@override_settings(YECAO_V1_INSTALL_PENDING=False)
class V1SetupWizardFlowTests(TestCase):
    def setUp(self):
        self.client = Client()

    def _post_step(self, slug, data):
        return self.client.post(reverse('v1_setup_step', kwargs={'step_slug': slug}), data)

    def test_full_wizard_creates_v1_shop(self):
        self.assertFalse(v1_setup_completed())
        welcome = self.client.get(reverse('v1_setup_entry'))
        self.assertEqual(welcome.status_code, 302)

        r2 = self._post_step(
            'shop',
            {
                'shop_name': '向导测试店',
                'username': 'v1_boss_user',
                'password1': 'BossPass12345',
                'password2': 'BossPass12345',
                'address': '测试路 1 号',
            },
        )
        self.assertEqual(r2.status_code, 302)
        self.assertIn('/network/', r2['Location'])

        r3 = self._post_step(
            'network',
            {'listen_port': '8000', 'lan_base_url': 'http://192.168.1.88:8000'},
        )
        self.assertEqual(r3.status_code, 302)

        r4 = self._post_step('plugins', {})
        self.assertEqual(r4.status_code, 302)

        r5 = self._post_step(
            'payment',
            {
                'enable_cash': 'on',
                'enable_simulate': 'on',
            },
        )
        self.assertEqual(r5.status_code, 302)

        r6 = self._post_step('backup', {'backup_dir': 'D:\\YecaoBackup'})
        self.assertEqual(r6.status_code, 302)

        r7 = self._post_step('done', {})
        self.assertEqual(r7.status_code, 200)
        self.assertContains(r7, '向导测试店')

        site = get_site_settings()
        self.assertTrue(site.v1_setup_completed)
        self.assertEqual(site.install_mode, INSTALL_MODE_V1_LOCAL)
        self.assertTrue(v1_local_mode_enabled())
        self.assertEqual(site.v1_backup_dir, 'D:\\YecaoBackup')

        profile = ShopProfile.objects.get(seller_id='v1_boss_user')
        self.assertEqual(profile.shop_name, '向导测试店')
        operating = get_operating_settings('v1_boss_user')
        self.assertTrue(operating.plugin_dining_enabled)
        self.assertFalse(operating.plugin_fulfillment_enabled)
        self.assertTrue(is_plugin_enabled('dining', 'v1_boss_user'))
        self.assertFalse(is_plugin_enabled('fulfillment', 'v1_boss_user'))

    @override_settings(YECAO_V1_INSTALL_PENDING=True)
    def test_auto_redirect_to_wizard(self):
        resp = self.client.get('/accounts/login/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/v1-local/setup/', resp['Location'])

    def test_blocked_when_shop_already_exists(self):
        create_test_shop_bundle(username='block_v1_setup')
        resp = self.client.get(reverse('v1_setup_entry'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp['Location'])

    @override_settings(YECAO_V1_INSTALL_PENDING=True)
    def test_plugins_can_enable_fulfillment(self):
        self._post_step(
            'shop',
            {
                'shop_name': '履约开测试店',
                'username': 'v1_fulfill_boss',
                'password1': 'BossPass12345',
                'password2': 'BossPass12345',
            },
        )
        self._post_step(
            'network',
            {'listen_port': '8000', 'lan_base_url': 'http://192.168.1.50:8000'},
        )
        self._post_step('plugins', {'enable_fulfillment': 'on'})
        self._post_step('payment', {'enable_cash': 'on'})
        self._post_step('backup', {'backup_dir': 'C:\\backup'})
        self._post_step('done', {})
        operating = get_operating_settings('v1_fulfill_boss')
        self.assertTrue(operating.plugin_fulfillment_enabled)


class V1SetupPrefillAndSessionTests(TestCase):
    def test_network_form_fills_empty_lan_initial(self):
        form = V1SetupNetworkForm(initial={'listen_port': 8000, 'lan_base_url': ''})
        # 探测成功则有 http；失败则空串（不得出现 127.0.0.1）
        filled = form.initial.get('lan_base_url') or ''
        self.assertNotIn('127.0.0.1', filled)
        if filled:
            self.assertTrue(filled.startswith('http://'))
            self.assertIn(':8000', filled)

    def test_backup_form_fills_empty_initial(self):
        form = V1SetupBackupForm(initial={'backup_dir': ''})
        self.assertTrue((form.initial.get('backup_dir') or '').endswith('backup'))

    def test_backup_empty_post_uses_default(self):
        form = V1SetupBackupForm(data={'backup_dir': ''})
        self.assertTrue(form.is_valid())
        self.assertTrue(form.cleaned_data['backup_dir'].endswith('backup'))

    def test_reject_loopback_lan_url(self):
        form = V1SetupNetworkForm(
            data={'listen_port': '8000', 'lan_base_url': 'http://127.0.0.1:8000'},
        )
        self.assertFalse(form.is_valid())
        self.assertIn('lan_base_url', form.errors)

    @override_settings()
    def test_detect_fail_default_lan_empty(self):
        from unittest.mock import patch

        with patch('waimai.v1_setup_helpers.detect_lan_ip', return_value=None):
            from waimai.v1_setup_helpers import default_lan_base_url

            self.assertEqual(default_lan_base_url(8000), '')

    def test_setup_path_extends_session_to_15_minutes(self):
        client = Client()
        resp = client.get(reverse('v1_setup_entry'))
        self.assertEqual(resp.status_code, 302)
        session = client.session
        # Django 把整数过期写在会话里；向导应为 15 分钟
        expiry = session.get_expiry_age()
        self.assertGreaterEqual(expiry, V1_SETUP_SESSION_SECONDS - 5)
        self.assertLessEqual(expiry, V1_SETUP_SESSION_SECONDS)
