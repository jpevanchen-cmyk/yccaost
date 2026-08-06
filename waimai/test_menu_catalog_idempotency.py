# 幂等第 4 步：卖家清单 Panel 防重复开关/上限

from django.test import TestCase
from django.urls import reverse

from waimai.panel_refresh_helpers import PANEL_REQUEST_HEADER
from waimai.test_shop_helpers import create_logged_in_seller_client, create_test_shop_bundle


class MenuCatalogIdempotencyTests(TestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            with_menu=True,
            with_dish=True,
            dish_name='清单幂等商品',
        )
        self.seller = bundle.seller
        self.profile = bundle.profile
        self.dish = bundle.dish
        self.item = bundle.item
        self.client = create_logged_in_seller_client(bundle)
        self.products_url = reverse('seller_panel_section', kwargs={'section': 'products'})
        self.panel_headers = {'HTTP_X_REQUESTED_WITH': PANEL_REQUEST_HEADER}

    def _toggle_listed_payload(self, key: str = ''):
        data = {
            'toggle_menu_item_listed': '1',
            'profile_id': str(self.profile.profile_id),
            'item_id': str(self.item.item_id),
        }
        if key:
            data['idempotency_key'] = key
        return data

    def test_same_key_toggle_listed_only_flips_once(self):
        key = 'menu-toggle-key-00000001'
        payload = self._toggle_listed_payload(key)

        resp1 = self.client.post(self.products_url, payload, **self.panel_headers)
        resp2 = self.client.post(self.products_url, payload, **self.panel_headers)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp1.json()['html'], resp2.json()['html'])

        self.item.refresh_from_db()
        self.assertFalse(self.item.is_listed)

    def test_without_key_two_toggles_flip_twice(self):
        payload = self._toggle_listed_payload()

        self.client.post(self.products_url, payload, **self.panel_headers)
        self.client.post(self.products_url, payload, **self.panel_headers)

        self.item.refresh_from_db()
        self.assertTrue(self.item.is_listed)

    def test_same_key_save_cap_only_writes_once(self):
        key = 'menu-cap-key-00000001'
        payload = {
            'save_menu_item_cap': '1',
            'profile_id': str(self.profile.profile_id),
            'item_id': str(self.item.item_id),
            'sales_cap': '88',
            'idempotency_key': key,
        }

        self.client.post(self.products_url, payload, **self.panel_headers)
        self.client.post(self.products_url, payload, **self.panel_headers)

        self.item.refresh_from_db()
        self.assertEqual(self.item.sales_cap, 88)
