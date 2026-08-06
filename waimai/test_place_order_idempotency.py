# 幂等第 2 步：正式下单 place_order 防双单

from datetime import time
from decimal import Decimal

from django.test import Client, TestCase

from waimai.channel_helpers import channel_session_key
from waimai.models import BuyOrder, User
from waimai.operating_helpers import get_operating_settings
from waimai.order_helpers import cart_line_key, normalize_cart_keys, set_shop_cart
from waimai.test_shop_helpers import create_test_shop_bundle


class PlaceOrderIdempotencyTests(TestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='idem_seller',
            password='seller-pass-123',
            shop_code='idemshop',
            shop_name='幂等试验店',
            with_menu=True,
            with_dish=True,
            dish_name='幂等试验菜',
            dish_price=Decimal('12.00'),
        )
        self.seller = bundle.seller
        self.dish = bundle.dish
        self.buyer = User.objects.create_user(
            username='idem_buyer', password='buyer-pass-123', role='buyer',
        )
        settings = get_operating_settings(self.seller.username)
        settings.plugin_dining_enabled = True
        settings.takeaway_channel_enabled = True
        # 测试可能在凌晨跑，须放宽营业时段，否则 check_order_admission 拒单
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=[
            'plugin_dining_enabled', 'takeaway_channel_enabled',
            'business_open', 'business_close',
        ])

    def _client_ready(self):
        client = Client()
        client.login(username=self.buyer.username, password='buyer-pass-123')
        line_key = cart_line_key(self.dish.dish_id, 'general')
        cart = normalize_cart_keys({line_key: 1})
        session = client.session
        session[channel_session_key(self.seller.username)] = 'takeaway'
        set_shop_cart(session, self.seller.username, cart)
        session.save()
        return client

    def _place_payload(self, key: str = ''):
        data = {
            'seller_id': self.seller.username,
            'fulfillment_type': 'takeaway',
            'distance_km': '0',
            'delivery_address': '',
        }
        if key:
            data['idempotency_key'] = key
        return data

    def test_same_idempotency_key_creates_one_order(self):
        client = self._client_ready()
        key = 'place-order-key-001'
        payload = self._place_payload(key)

        resp1 = client.post('/place-order/', payload)
        resp2 = client.post('/place-order/', payload)

        self.assertEqual(resp1.status_code, 302)
        self.assertEqual(resp2.status_code, 302)
        self.assertEqual(resp1['Location'], resp2['Location'])
        self.assertEqual(
            BuyOrder.objects.filter(
                seller_id=self.seller.username, buyer_id=self.buyer.username,
            ).count(),
            1,
        )

    def test_without_key_second_submit_empty_cart_no_double_order(self):
        client = self._client_ready()
        payload = self._place_payload()

        resp1 = client.post('/place-order/', payload)
        self.assertEqual(resp1.status_code, 302)
        resp2 = client.post('/place-order/', payload)
        self.assertEqual(resp2.status_code, 302)
        self.assertIn('/shop/', resp2['Location'])
        self.assertEqual(
            BuyOrder.objects.filter(
                seller_id=self.seller.username, buyer_id=self.buyer.username,
            ).count(),
            1,
        )
