# 店铺注销第一刀

from datetime import time
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from waimai.models import BuyOrder, ShopProfile
from waimai.operating_helpers import get_operating_settings
from waimai.shop_cancel_helpers import (
    cancel_shop_for_owner,
    shop_cancel_block_reason,
    shop_is_cancelled,
)
from waimai.test_shop_helpers import create_test_shop_bundle


class ShopCancelFirstKnifeTests(TestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='scancel_seller',
            password='seller-pass-123',
            shop_code='scancel',
            shop_name='注销测试店',
            with_menu=True,
            with_dish=True,
            dish_name='注销测菜',
            dish_price=Decimal('8.00'),
        )
        self.seller = bundle.seller
        self.shop = bundle.shop
        self.dish = bundle.dish
        self.client = Client()
        ops = get_operating_settings(self.seller.username)
        ops.business_open = time(0, 0)
        ops.business_close = time(23, 59)
        ops.save()

    def test_block_when_open_order(self):
        BuyOrder.objects.create(
            buyer_id='someone',
            seller_id=self.seller.username,
            total_amount=Decimal('8.00'),
            subtotal_amount=Decimal('8.00'),
            delivery_fee=Decimal('0.00'),
            dish_items=[],
            payment_status='paid',
            order_status='awaiting_prep',
            delivery_address='【打包自取】',
            fulfillment_type='takeaway',
        )
        msg = shop_cancel_block_reason(self.seller, self.shop)
        self.assertIn('进行中', msg)

    def test_soft_cancel_hides_from_directory_and_blocks_shop(self):
        self.assertEqual(shop_cancel_block_reason(self.seller, self.shop), '')
        tip = cancel_shop_for_owner(self.seller)
        self.assertIn('已注销', tip)
        self.shop.refresh_from_db()
        self.assertTrue(shop_is_cancelled(self.shop))
        self.assertFalse(self.shop.is_listed)

        resp = self.client.get(f'/shop/?seller_id={self.seller.username}')
        self.assertEqual(resp.status_code, 302)

        listed = ShopProfile.objects.filter(
            is_listed=True, cancelled_at__isnull=True,
            seller_id=self.seller.username,
        ).exists()
        self.assertFalse(listed)

    def test_post_cancel_page_idempotent_message(self):
        self.client.login(username='scancel_seller', password='seller-pass-123')
        url = reverse('shop_cancel')
        resp = self.client.post(url, {
            'current_password': 'seller-pass-123',
            'confirm_cancel': 'on',
            'export_ack': 'on',
            'idempotency_key': 'shop-cancel-test-001',
        })
        self.assertEqual(resp.status_code, 302)
        self.shop.refresh_from_db()
        self.assertTrue(shop_is_cancelled(self.shop))

        resp2 = self.client.get(url)
        self.assertContains(resp2, '已经注销')
