# 幂等第 3 步：客人购物车 Panel 防重复加减

from datetime import time

from django.test import Client, TestCase

from waimai.channel_helpers import channel_session_key
from waimai.operating_helpers import get_operating_settings
from waimai.order_helpers import cart_line_key, get_shop_cart
from waimai.panel_refresh_helpers import PANEL_REQUEST_HEADER
from waimai.test_shop_helpers import create_test_shop_bundle


class ShopCartIdempotencyTests(TestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='cart_idem_seller',
            password='seller-pass-123',
            shop_code='cartidem',
            shop_name='购物车幂等试验店',
            with_dish=True,
            dish_name='幂等加购菜',
        )
        self.seller = bundle.seller
        self.dish = bundle.dish
        settings = get_operating_settings(self.seller.username)
        settings.plugin_dining_enabled = False
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=[
            'plugin_dining_enabled', 'business_open', 'business_close',
        ])

    def _panel_client(self):
        client = Client()
        session = client.session
        session[channel_session_key(self.seller.username)] = 'order'
        session.save()
        return client

    def _add_payload(self, key: str = ''):
        data = {
            'action': 'add_to_cart',
            'dish_id': str(self.dish.dish_id),
            'price_tier': 'general',
        }
        if key:
            data['idempotency_key'] = key
        return data

    def test_same_key_add_to_cart_only_increments_once(self):
        client = self._panel_client()
        key = 'cart-add-key-00000001'
        url = f'/shop/?seller_id={self.seller.username}'
        headers = {'HTTP_X_REQUESTED_WITH': PANEL_REQUEST_HEADER}

        resp1 = client.post(url, self._add_payload(key), **headers)
        resp2 = client.post(url, self._add_payload(key), **headers)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp1.json()['html'], resp2.json()['html'])

        line_key = cart_line_key(self.dish.dish_id, 'general')
        cart = get_shop_cart(client.session, self.seller.username)
        self.assertEqual(cart.get(line_key), 1)

    def test_without_key_two_adds_increment_twice(self):
        client = self._panel_client()
        url = f'/shop/?seller_id={self.seller.username}'
        headers = {'HTTP_X_REQUESTED_WITH': PANEL_REQUEST_HEADER}

        client.post(url, self._add_payload(), **headers)
        client.post(url, self._add_payload(), **headers)

        line_key = cart_line_key(self.dish.dish_id, 'general')
        cart = get_shop_cart(client.session, self.seller.username)
        self.assertEqual(cart.get(line_key), 2)

    def test_same_key_decrease_only_once(self):
        client = self._panel_client()
        url = f'/shop/?seller_id={self.seller.username}'
        headers = {'HTTP_X_REQUESTED_WITH': PANEL_REQUEST_HEADER}
        line_key = cart_line_key(self.dish.dish_id, 'general')

        client.post(url, self._add_payload(), **headers)
        client.post(url, self._add_payload(), **headers)
        self.assertEqual(get_shop_cart(client.session, self.seller.username).get(line_key), 2)

        key = 'cart-dec-key-00000001'
        dec_payload = {
            'action': 'decrease_from_cart',
            'line_key': line_key,
            'idempotency_key': key,
        }
        client.post(url, dec_payload, **headers)
        client.post(url, dec_payload, **headers)

        cart = get_shop_cart(client.session, self.seller.username)
        self.assertEqual(cart.get(line_key), 1)
