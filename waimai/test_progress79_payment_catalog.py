# 进度 79：清单可售名额 · 付款后占用

from datetime import time
from decimal import Decimal

from django.test import TestCase

from waimai.menu_helpers import (
    aggregate_dish_quantities_from_order,
    ensure_active_menu_catalog,
    release_catalog_sales_for_order,
    sync_new_dish_to_menu_profiles,
    try_apply_catalog_sales_for_order,
)
from waimai.models import BuyOrder, Dish, MenuProfileItem, ShopProfile, User
from waimai.operating_helpers import get_operating_settings
from waimai.payments.core import get_payment_settings
from waimai.payments.service import initiate_payment


class CatalogSalesPaymentTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='cap79_seller', password='seller-pass-123', role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='名额试验店',
            shop_code='cap79',
            address='试验地址',
        )
        settings = get_operating_settings(self.seller.username)
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=['business_open', 'business_close'])
        self.profile = ensure_active_menu_catalog(self.seller.username)
        self.dish = Dish.objects.create(
            seller_id=self.seller.username,
            name='限量菜',
            price=Decimal('10.00'),
            is_active=True,
        )
        sync_new_dish_to_menu_profiles(self.dish)
        self.menu_item = MenuProfileItem.objects.get(profile=self.profile, dish=self.dish)
        self.menu_item.is_listed = True
        self.menu_item.sales_cap = 2
        self.menu_item.sold_count = 0
        self.menu_item.save(update_fields=['is_listed', 'sales_cap', 'sold_count'])
        pay = get_payment_settings(self.seller.username)
        pay.enable_cash = True
        pay.enable_simulate = True
        pay.save(update_fields=['enable_cash', 'enable_simulate'])
        self.buyer = User.objects.create_user(
            username='cap79_buyer', password='buyer-pass-123', role='buyer',
        )

    def _make_order(self, qty: int) -> BuyOrder:
        return BuyOrder.objects.create(
            buyer_id=self.buyer.username,
            seller_id=self.seller.username,
            total_amount=Decimal('10.00') * qty,
            subtotal_amount=Decimal('10.00') * qty,
            dish_items=[{
                'line_id': 'abc',
                'dish_id': self.dish.dish_id.hex,
                'name': self.dish.name,
                'price': 10.0,
                'quantity': qty,
                'price_tier': 'general',
            }],
            payment_status='pending_payment',
            order_status='created',
            fulfillment_type='takeaway',
        )

    def test_order_create_does_not_increment_sold_count(self):
        order = self._make_order(1)
        self.menu_item.refresh_from_db()
        self.assertEqual(self.menu_item.sold_count, 0)
        self.assertFalse(order.catalog_sales_applied)

    def test_cash_payment_selection_applies_catalog_sales(self):
        order = self._make_order(1)
        result = initiate_payment(order, 'cash', '127.0.0.1')
        self.assertTrue(result.ok)
        self.menu_item.refresh_from_db()
        self.assertEqual(self.menu_item.sold_count, 1)
        order.refresh_from_db()
        self.assertTrue(order.catalog_sales_applied)

    def test_cash_payment_rejects_when_cap_exceeded(self):
        self.menu_item.sold_count = 2
        self.menu_item.save(update_fields=['sold_count'])
        order = self._make_order(1)
        result = initiate_payment(order, 'cash', '127.0.0.1')
        self.assertFalse(result.ok)
        self.assertTrue(result.messages)
        self.assertIn('限量菜', result.messages[0])
        self.menu_item.refresh_from_db()
        self.assertEqual(self.menu_item.sold_count, 2)

    def test_simulate_payment_does_not_apply_catalog_sales(self):
        order = self._make_order(1)
        initiate_payment(order, 'wechat_simulate', '127.0.0.1')
        self.menu_item.refresh_from_db()
        self.assertEqual(self.menu_item.sold_count, 0)
        order.refresh_from_db()
        self.assertFalse(order.catalog_sales_applied)

    def test_simulate_after_cash_releases_catalog_sales(self):
        order = self._make_order(1)
        initiate_payment(order, 'cash', '127.0.0.1')
        self.menu_item.refresh_from_db()
        self.assertEqual(self.menu_item.sold_count, 1)
        initiate_payment(order, 'wechat_simulate', '127.0.0.1')
        self.menu_item.refresh_from_db()
        self.assertEqual(self.menu_item.sold_count, 0)

    def test_cancel_releases_applied_catalog_sales(self):
        order = self._make_order(2)
        ok, _ = try_apply_catalog_sales_for_order(order)
        self.assertTrue(ok)
        self.menu_item.refresh_from_db()
        self.assertEqual(self.menu_item.sold_count, 2)
        release_catalog_sales_for_order(order)
        self.menu_item.refresh_from_db()
        self.assertEqual(self.menu_item.sold_count, 0)

    def test_merge_delta_apply_on_existing_order(self):
        order = self._make_order(1)
        ok, _ = try_apply_catalog_sales_for_order(order)
        self.assertTrue(ok)
        order.dish_items = [{
            'line_id': 'abc',
            'dish_id': self.dish.dish_id.hex,
            'name': self.dish.name,
            'price': 10.0,
            'quantity': 2,
            'price_tier': 'general',
        }]
        order.save(update_fields=['dish_items', 'updated_at'])
        ok, errors = try_apply_catalog_sales_for_order(order)
        self.assertTrue(ok, errors)
        self.menu_item.refresh_from_db()
        self.assertEqual(self.menu_item.sold_count, 2)
        totals = aggregate_dish_quantities_from_order(order)
        self.assertEqual(totals[self.dish.dish_id.hex], 2)
