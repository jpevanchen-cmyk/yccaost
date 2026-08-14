# 店内地址唯一真源：堂食 table_lan；本机打开后台走 127

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from waimai.lan_base_helpers import (
    apply_shop_lan_base_url,
    get_shop_lan_base_url,
    local_open_backend_url,
)
from waimai.operating_helpers import get_operating_settings, resolve_shop_access_base_url
from waimai.owner_helpers import get_site_settings
from waimai.test_shop_helpers import create_test_shop_bundle


class LanBaseTrueSourceTests(TestCase):
    def setUp(self):
        self.bundle = create_test_shop_bundle(username='lan_src_boss')
        self.seller_id = self.bundle.seller.username

    def test_get_prefers_table_lan_not_v1_copy(self):
        op = get_operating_settings(self.seller_id)
        op.table_lan_base_url = 'http://192.168.3.120:8000'
        op.save(update_fields=['table_lan_base_url'])
        site = get_site_settings()
        site.v1_lan_base_url = 'http://10.0.0.9:8000'
        site.save(update_fields=['v1_lan_base_url'])
        self.assertEqual(get_shop_lan_base_url(self.seller_id), 'http://192.168.3.120:8000')

    def test_legacy_fallback_when_table_lan_empty(self):
        op = get_operating_settings(self.seller_id)
        op.table_lan_base_url = ''
        op.save(update_fields=['table_lan_base_url'])
        site = get_site_settings()
        site.v1_lan_base_url = 'http://192.168.1.50:8000'
        site.save(update_fields=['v1_lan_base_url'])
        self.assertEqual(get_shop_lan_base_url(self.seller_id), 'http://192.168.1.50:8000')

    def test_apply_writes_table_lan_not_v1_field(self):
        site = get_site_settings()
        site.v1_lan_base_url = 'http://10.0.0.9:8000'
        site.save(update_fields=['v1_lan_base_url'])
        ok, msg = apply_shop_lan_base_url(self.seller_id, 'http://192.168.3.88:8000')
        self.assertTrue(ok, msg)
        op = get_operating_settings(self.seller_id)
        self.assertEqual(op.table_lan_base_url, 'http://192.168.3.88:8000')
        site.refresh_from_db()
        self.assertEqual(site.v1_lan_base_url, 'http://10.0.0.9:8000')

    def test_apply_same_url_twice_is_ok(self):
        ok1, _ = apply_shop_lan_base_url(self.seller_id, 'http://192.168.3.88:8000')
        ok2, msg2 = apply_shop_lan_base_url(self.seller_id, 'http://192.168.3.88:8000')
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertIn('未变化', msg2)

    def test_apply_rejects_loopback(self):
        ok, msg = apply_shop_lan_base_url(self.seller_id, 'http://127.0.0.1:8000')
        self.assertFalse(ok)
        self.assertIn('127', msg)

    def test_resolve_uses_true_source(self):
        apply_shop_lan_base_url(self.seller_id, 'http://192.168.3.120:8000')
        req = self.client.get('/', HTTP_HOST='127.0.0.1:8000').wsgi_request
        self.assertEqual(
            resolve_shop_access_base_url(req, self.seller_id),
            'http://192.168.3.120:8000',
        )

    def test_local_open_backend_is_loopback(self):
        self.assertEqual(local_open_backend_url(8000), 'http://127.0.0.1:8000/accounts/login/')


class LauncherConfigOpenUrlTests(TestCase):
    def test_open_url_stays_127_when_lan_saved(self):
        bundle = create_test_shop_bundle(username='lan_tray_boss')
        apply_shop_lan_base_url(bundle.seller.username, 'http://192.168.3.120:8000')
        out = StringIO()
        call_command('yecao_launcher_config', stdout=out)
        import json

        data = json.loads(out.getvalue())
        self.assertTrue(data['open_url'].startswith('http://127.0.0.1:'))
        self.assertIn('/accounts/login/', data['open_url'])
        self.assertEqual(data['lan_base_url'], 'http://192.168.3.120:8000')
        self.assertNotIn('192.168.3.120', data['open_url'])


class DineLanCompareAjaxTests(TestCase):
    def setUp(self):
        self.bundle = create_test_shop_bundle(username='lan_dine_boss')
        self.seller_id = self.bundle.seller.username
        op = get_operating_settings(self.seller_id)
        op.plugin_dining_enabled = True
        op.save(update_fields=['plugin_dining_enabled'])
        self.client = Client()
        self.client.force_login(self.bundle.seller)
        self.dine_url = reverse('seller_panel_section', kwargs={'section': 'dine'})

    @override_settings(DEBUG=True)
    def test_dine_page_shows_compare(self):
        resp = self.client.get(self.dine_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '检测当前 IP')
        self.assertContains(resp, '一键更新为当前')

    @override_settings(DEBUG=True)
    def test_lan_compare_json(self):
        apply_shop_lan_base_url(self.seller_id, 'http://192.168.3.120:8000')
        with patch('waimai.lan_base_helpers.detect_current_lan_base_url', return_value='http://192.168.3.99:8000'):
            resp = self.client.get(
                self.dine_url + '?lan_compare=1',
                HTTP_ACCEPT='application/json',
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['saved_lan'], 'http://192.168.3.120:8000')
        self.assertEqual(data['detected_lan'], 'http://192.168.3.99:8000')
        self.assertFalse(data['match'])

    @override_settings(DEBUG=True)
    def test_apply_detected_lan_post_csrf_and_idempotent(self):
        with patch(
            'waimai.lan_base_helpers.detect_current_lan_base_url',
            return_value='http://192.168.3.77:8000',
        ):
            resp = self.client.post(
                self.dine_url,
                {'apply_detected_lan': '1', 'idempotency_key': 'lan-apply-key-001'},
                HTTP_ACCEPT='application/json',
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            )
            self.assertEqual(resp.status_code, 200, resp.content)
            self.assertTrue(resp.json().get('ok'))
            resp2 = self.client.post(
                self.dine_url,
                {'apply_detected_lan': '1', 'idempotency_key': 'lan-apply-key-001'},
                HTTP_ACCEPT='application/json',
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            )
        self.assertEqual(resp2.status_code, 200)
        op = get_operating_settings(self.seller_id)
        self.assertEqual(op.table_lan_base_url, 'http://192.168.3.77:8000')
        site = get_site_settings()
        self.assertFalse(site.v1_lan_base_url)

    @override_settings(DEBUG=True)
    def test_apply_without_csrf_is_403(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.bundle.seller)
        resp = client.post(
            self.dine_url,
            {'apply_detected_lan': '1'},
            HTTP_ACCEPT='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 403)

    @override_settings(DEBUG=False)
    def test_cloud_like_debug_off_hides_one_click(self):
        resp = self.client.get(self.dine_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, '一键更新为当前')
