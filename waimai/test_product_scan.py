# 批次 G · G1-6：商品分档二维码扫码加购

from datetime import time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from waimai.models import Dish, ShopProfile
from waimai.operating_helpers import get_operating_settings
from waimai.product_helpers import PRICE_TIER_GENERAL, PRICE_TIER_MEMBER
from waimai.product_scan_helpers import (
    build_product_scan_path,
    evaluate_product_scan,
    resolve_dish_for_scan,
)

User = get_user_model()


class ProductScanTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='scan_seller',
            password='test-pass',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='扫码试验店',
            shop_code='SCANS',
            address='试验地址',
        )
        settings = get_operating_settings(self.seller.username)
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.plugin_dining_enabled = False
        settings.save(update_fields=['business_open', 'business_close', 'plugin_dining_enabled'])
        self.buyer = User.objects.create_user(
            username='scan_buyer',
            password='test-pass',
            role='buyer',
        )
        self.dish = Dish.objects.create(
            seller_id=self.seller.username,
            name='扫码测试商品',
            price=Decimal('18.00'),
            is_active=True,
        )
        self.client = Client()

    def test_build_product_scan_path(self):
        path = build_product_scan_path(
            self.seller.username,
            self.dish.display_code,
            PRICE_TIER_GENERAL,
        )
        self.assertIn('/shop/scan/', path)
        self.assertIn(f'seller_id={self.seller.username}', path)
        self.assertIn(self.dish.display_code, path)

    def test_inactive_dish_is_unavailable(self):
        self.dish.is_active = False
        self.dish.save(update_fields=['is_active'])
        found = resolve_dish_for_scan(self.seller.username, self.dish.display_code)
        self.assertIsNone(found)

    def test_scan_requires_login(self):
        url = reverse(
            'product_scan_add',
            kwargs={'display_code': self.dish.display_code, 'tier': PRICE_TIER_GENERAL},
        )
        resp = self.client.get(url, {'seller_id': self.seller.username})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '请先登录买家账号')
        self.assertContains(resp, '去登录')

    def test_scan_adds_to_cart_when_logged_in(self):
        self.client.login(username='scan_buyer', password='test-pass')
        url = reverse(
            'product_scan_add',
            kwargs={'display_code': self.dish.display_code, 'tier': PRICE_TIER_GENERAL},
        )
        resp = self.client.get(url, {'seller_id': self.seller.username}, follow=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('seller_id=' + self.seller.username, resp['Location'])

        session = self.client.session
        cart = session.get('carts', {}).get(self.seller.username, {})
        line_key = f'{self.dish.dish_id}|{PRICE_TIER_GENERAL}'
        self.assertEqual(cart.get(line_key), 1)

    def test_member_tier_unavailable_without_member_price(self):
        status, msg = evaluate_product_scan(self.dish, PRICE_TIER_MEMBER, self.seller.username)
        self.assertEqual(status, 'unavailable')
        self.assertEqual(msg, '无商品')

    def test_member_tier_available_when_enabled(self):
        self.dish.member_price_enabled = True
        self.dish.member_price_mode = 'percent'
        self.dish.member_price_percent = Decimal('90')
        self.dish.save()
        status, msg = evaluate_product_scan(self.dish, PRICE_TIER_MEMBER, self.seller.username)
        self.assertEqual(status, 'ok')
        self.assertEqual(msg, '')
