# 进度 67-①：游客打包/外卖未登录下单（本机自测）

from datetime import time
from decimal import Decimal

from django.test import Client, TestCase

from waimai.channel_helpers import channel_session_key
from waimai.models import BuyOrder
from waimai.operating_helpers import get_operating_settings
from waimai.order_helpers import cart_line_key, normalize_cart_keys, set_shop_cart
from waimai.plugins.dining.guest_order_helpers import (
    guest_remote_checkout_allowed,
    parse_guest_contact,
)
from waimai.test_shop_helpers import create_test_shop_bundle


class GuestRemoteCheckout67Tests(TestCase):
    """游客打包/外卖：开关默认关；开后可结算并认领看单。"""

    def setUp(self):
        bundle = create_test_shop_bundle(
            username='guest67_seller',
            password='seller-pass-123',
            shop_code='g67shop',
            shop_name='游客下单测试店',
            with_menu=True,
            with_dish=True,
            dish_name='游客测菜',
            dish_price=Decimal('12.00'),
        )
        self.seller_id = bundle.seller.username
        self.dish = bundle.dish
        self.ops = get_operating_settings(self.seller_id)
        self.ops.plugin_dining_enabled = True
        self.ops.takeaway_channel_enabled = True
        self.ops.delivery_channel_enabled = True
        self.ops.business_open = time(0, 0)
        self.ops.business_close = time(23, 59)
        # 三开关默认关（模型默认 False）
        self.ops.guest_takeaway_enabled = False
        self.ops.guest_delivery_online_enabled = False
        self.ops.guest_delivery_cod_enabled = False
        self.ops.save()
        self.client = Client()

    def _session_with_takeaway_cart(self):
        line_key = cart_line_key(self.dish.dish_id, 'general')
        cart = normalize_cart_keys({line_key: 1})
        session = self.client.session
        session[channel_session_key(self.seller_id)] = 'takeaway'
        set_shop_cart(session, self.seller_id, cart)
        session.save()

    def test_switches_default_off(self):
        ok, msg = guest_remote_checkout_allowed(self.seller_id, 'takeaway')
        self.assertFalse(ok)
        self.assertIn('未登录打包', msg)
        ok2, _ = guest_remote_checkout_allowed(self.seller_id, 'delivery')
        self.assertFalse(ok2)

    def test_takeaway_switch_allows(self):
        self.ops.guest_takeaway_enabled = True
        self.ops.save(update_fields=['guest_takeaway_enabled'])
        ok, msg = guest_remote_checkout_allowed(self.seller_id, 'takeaway')
        self.assertTrue(ok)
        self.assertEqual(msg, '')

    def test_parse_guest_contact_requires_name_phone(self):
        parsed, err = parse_guest_contact({
            'guest_contact_name': '',
            'guest_contact_phone': '13800138000',
        })
        self.assertIsNone(parsed)
        self.assertIn('姓名', err)
        parsed2, err2 = parse_guest_contact({
            'guest_contact_name': '张三',
            'guest_contact_phone': '13800138000',
            'guest_contact_email': '',
        })
        self.assertIsNotNone(parsed2)
        self.assertEqual(err2, '')
        self.assertEqual(parsed2['name'], '张三')

    def test_guest_cannot_checkout_when_switch_off(self):
        self._session_with_takeaway_cart()
        resp = self.client.post(
            f'/shop/?seller_id={self.seller_id}',
            {'action': 'checkout'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '未登录打包')

    def test_guest_place_takeaway_and_claim(self):
        self.ops.guest_takeaway_enabled = True
        self.ops.save(update_fields=['guest_takeaway_enabled'])
        self._session_with_takeaway_cart()

        resp = self.client.post(
            f'/shop/?seller_id={self.seller_id}',
            {'action': 'checkout'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '顾客联系信息')
        self.assertContains(resp, 'guest_contact_name')

        resp2 = self.client.post('/place-order/', {
            'seller_id': self.seller_id,
            'fulfillment_type': 'takeaway',
            'distance_km': '0',
            'delivery_address': '',
            'guest_contact_name': '李四',
            'guest_contact_phone': '13900139000',
            'guest_contact_email': 'li@example.com',
            'idempotency_key': 'guest67-takeaway-001',
        })
        self.assertEqual(resp2.status_code, 302)
        self.assertIn('/voucher/', resp2['Location'])

        order = BuyOrder.objects.filter(seller_id=self.seller_id).latest('created_at')
        self.assertEqual(order.buyer_id, '')
        self.assertEqual(order.guest_contact_name, '李四')
        self.assertEqual(order.guest_contact_phone, '13900139000')
        self.assertEqual(order.fulfillment_type, 'takeaway')

        voucher = self.client.get(resp2['Location'])
        self.assertEqual(voucher.status_code, 200)
        self.assertContains(voucher, '订单凭证')
        self.assertContains(voucher, '请立刻截图或打印保存')
        self.assertContains(voucher, '李四')
        self.assertContains(voucher, '去支付')
        self.assertContains(voucher, '付完款或选定现金/货到付款后')
