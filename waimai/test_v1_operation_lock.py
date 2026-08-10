# V1 操作锁

from django.test import Client, TestCase
from django.urls import reverse

from waimai.owner_helpers import get_site_settings
from waimai.test_shop_helpers import create_logged_in_seller_client, create_test_shop_bundle
from waimai.operation_lock_helpers import (
    SESSION_OP_LOCK_ACTIVITY,
    set_operation_lock_pin,
    site_operation_lock_enabled,
)


class OperationLockTests(TestCase):
    def setUp(self):
        self.bundle = create_test_shop_bundle(username='op_lock_seller')
        self.user = self.bundle.seller
        self.user.is_server_owner = True
        self.user.save(update_fields=['is_server_owner'])
        self.client = create_logged_in_seller_client(self.bundle)
        site = get_site_settings()
        set_operation_lock_pin(site, '1234')
        site.operation_lock_enabled = True
        site.operation_lock_idle_seconds = 300
        site.save()

    def test_lock_shows_overlay_until_unlock(self):
        self.assertTrue(site_operation_lock_enabled())
        url = reverse('seller_panel_section', kwargs={'section': 'orders'})
        blocked = self.client.get(url)
        self.assertEqual(blocked.status_code, 200)
        self.assertContains(blocked, 'yc-operation-lock-overlay')
        self.assertContains(blocked, '店铺管理已锁定')

        unlock = self.client.post(
            reverse('operation_lock_unlock'),
            {'pin': '1234', 'ajax': '1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(unlock.status_code, 200)
        self.assertTrue(unlock.json()['ok'])

        ok = self.client.get(url)
        self.assertEqual(ok.status_code, 200)
        self.assertNotContains(ok, 'yc-operation-lock-overlay')

    def test_workbench_not_blocked(self):
        shop_code = self.bundle.shop.shop_code
        work_url = reverse('shop_work', kwargs={'shop_code': shop_code})
        resp = Client().get(work_url)
        self.assertEqual(resp.status_code, 200)

    def test_server_settings_not_blocked(self):
        settings_url = reverse('server_settings')
        resp = self.client.get(settings_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'yc-operation-lock-overlay')

    def test_manual_lock(self):
        url = reverse('seller_panel_section', kwargs={'section': 'orders'})
        self.client.post(
            reverse('operation_lock_unlock'),
            {'pin': '1234', 'ajax': '1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertNotContains(self.client.get(url), 'yc-operation-lock-overlay')
        locked = self.client.post(reverse('operation_lock_manual'), {'next': url})
        self.assertEqual(locked.status_code, 302)
        self.assertEqual(locked['Location'], url)
        overlay_page = self.client.get(url)
        self.assertContains(overlay_page, 'yc-operation-lock-overlay')

    def test_settings_in_seller_panel(self):
        settings_url = reverse('seller_panel_section', kwargs={'section': 'operation_lock'})
        self.client.post(
            reverse('operation_lock_unlock'),
            {'pin': '1234', 'ajax': '1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        resp = self.client.get(settings_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '操作锁')

    def test_old_server_settings_url_redirects(self):
        legacy = reverse('server_settings_operation_lock')
        resp = self.client.get(legacy)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/seller-panel/operation_lock/', resp['Location'])

    def test_touch_extends_session(self):
        url = reverse('seller_panel_section', kwargs={'section': 'orders'})
        self.client.post(
            reverse('operation_lock_unlock'),
            {'pin': '1234', 'ajax': '1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        before = float(self.client.session.get(SESSION_OP_LOCK_ACTIVITY, 0))
        self.client.post(reverse('operation_lock_touch'))
        after = float(self.client.session.get(SESSION_OP_LOCK_ACTIVITY, 0))
        self.assertGreaterEqual(after, before)

    def test_locked_post_to_seller_panel_blocked(self):
        url = reverse('seller_panel_section', kwargs={'section': 'orders'})
        resp = self.client.post(
            url,
            {'save_operating_status': '1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(resp.json()['operation_lock'])
