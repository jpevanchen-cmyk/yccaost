# 幂等第 12 步：Panel 超时「再试一次」后端契约（同一编号重发）

from django.test import TestCase
from django.urls import reverse

from waimai.panel_refresh_helpers import PANEL_REQUEST_HEADER
from waimai.test_shop_helpers import create_logged_in_seller_client, create_test_shop_bundle


class PanelTimeoutRetryIdempotencyTests(TestCase):
    """模拟超时后「再试一次」：同一 idempotency_key 连发两次，状态只改一次。"""

    def setUp(self):
        bundle = create_test_shop_bundle(with_menu=True, with_dish=True)
        self.item = bundle.item
        self.profile = bundle.profile
        self.client = create_logged_in_seller_client(bundle)
        self.products_url = reverse('seller_panel_section', kwargs={'section': 'products'})
        self.panel_headers = {'HTTP_X_REQUESTED_WITH': PANEL_REQUEST_HEADER}

    def test_menu_panel_retry_same_key_only_toggles_once(self):
        key = 'panel-retry-key-00000001'
        payload = {
            'toggle_menu_item_listed': '1',
            'profile_id': str(self.profile.profile_id),
            'item_id': str(self.item.item_id),
            'idempotency_key': key,
        }

        resp1 = self.client.post(self.products_url, payload, **self.panel_headers)
        resp2 = self.client.post(self.products_url, payload, **self.panel_headers)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp1.json()['ok'])
        self.assertTrue(resp2.json()['ok'])
        self.assertEqual(resp1.json()['html'], resp2.json()['html'])
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_listed)
