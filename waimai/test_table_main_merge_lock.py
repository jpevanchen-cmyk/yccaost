# 幂等第 8 步：桌码主单加点加锁（并发合并）

from datetime import time
from decimal import Decimal

from django.test import TransactionTestCase

from waimai.dine_models import ShopTable, TableSession
from waimai.menu_helpers import ensure_active_menu_catalog
from waimai.models import BuyOrder, Dish, MenuProfileItem
from waimai.operating_helpers import get_operating_settings
from waimai.test_shop_helpers import create_test_shop_bundle
from waimai.plugins.dining.table_main_merge_helpers import (
    merge_cart_into_table_main_order,
    place_or_merge_table_main_order,
)
from waimai.product_helpers import PRICE_TIER_GENERAL


class TableMainMergeLockTests(TransactionTestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='tm_merge_seller',
            password='seller-pass-123',
            shop_code='tmmerge',
            shop_name='加点锁试验店',
        )
        self.seller = bundle.seller
        settings = get_operating_settings(self.seller.username)
        settings.plugin_dining_enabled = True
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=[
            'plugin_dining_enabled', 'business_open', 'business_close',
        ])
        profile = ensure_active_menu_catalog(self.seller.username)
        self.dish_a = Dish.objects.create(
            seller_id=self.seller.username,
            name='合并试验菜A',
            price=Decimal('10.00'),
            is_active=True,
        )
        self.dish_b = Dish.objects.create(
            seller_id=self.seller.username,
            name='合并试验菜B',
            price=Decimal('15.00'),
            is_active=True,
        )
        MenuProfileItem.objects.update_or_create(
            profile=profile,
            dish=self.dish_a,
            defaults={'is_listed': True, 'general_price_listed': True},
        )
        MenuProfileItem.objects.update_or_create(
            profile=profile,
            dish=self.dish_b,
            defaults={'is_listed': True, 'general_price_listed': True},
        )
        self.table = ShopTable.objects.create(
            seller_id=self.seller.username,
            table_number='8',
            is_active=True,
        )
        self.session = TableSession.objects.create(
            seller_id=self.seller.username,
            shop_table=self.table,
            session_type='main',
            status='open',
        )
        self.pending_order = BuyOrder.objects.create(
            buyer_id='',
            seller_id=self.seller.username,
            total_amount=Decimal('10.00'),
            subtotal_amount=Decimal('10.00'),
            delivery_fee=Decimal('0'),
            dish_items=[{
                'line_id': 'line-a',
                'dish_id': self.dish_a.dish_id.hex,
                'name': self.dish_a.name,
                'price': 10.0,
                'quantity': 1,
                'price_tier': PRICE_TIER_GENERAL,
                'prepared_count': 0,
                'served_count': 0,
            }],
            payment_status='pending_payment',
            order_status='created',
            fulfillment_type='dine_in',
            delivery_address='堂食',
            distance_km=Decimal('0'),
            table_session=self.session,
            table_label='桌8',
            order_kind='table_main',
        )

    def _cart_item(self, dish, qty: int):
        return {
            'dish': dish,
            'quantity': qty,
            'unit_price': dish.price,
            'price_tier': PRICE_TIER_GENERAL,
        }

    def test_sequential_merge_accumulates_both_dishes(self):
        merged1 = merge_cart_into_table_main_order(
            self.session,
            [self._cart_item(self.dish_b, 2)],
            self.seller.username,
            Decimal('0'),
            'dine_in',
        )
        self.assertIsNotNone(merged1)
        merged2 = merge_cart_into_table_main_order(
            self.session,
            [self._cart_item(self.dish_a, 1)],
            self.seller.username,
            Decimal('0'),
            'dine_in',
        )
        self.assertIsNotNone(merged2)
        self.assertEqual(merged1.order_id, merged2.order_id)
        self.pending_order.refresh_from_db()
        self.assertEqual(self.pending_order.total_amount, Decimal('50.00'))
        qty_map = {
            row['dish_id']: row['quantity']
            for row in self.pending_order.dish_items
        }
        self.assertEqual(qty_map[self.dish_a.dish_id.hex], 2)
        self.assertEqual(qty_map[self.dish_b.dish_id.hex], 2)

    def test_place_or_merge_creates_when_no_pending(self):
        self.pending_order.payment_status = 'paid'
        self.pending_order.save(update_fields=['payment_status', 'updated_at'])

        def _create():
            return BuyOrder.objects.create(
                buyer_id='buyer_x',
                seller_id=self.seller.username,
                total_amount=Decimal('15.00'),
                subtotal_amount=Decimal('15.00'),
                delivery_fee=Decimal('0'),
                dish_items=[],
                payment_status='pending_payment',
                order_status='created',
                fulfillment_type='dine_in',
                delivery_address='堂食',
                distance_km=Decimal('0'),
                table_session=self.session,
                order_kind='table_main',
            )

        action, order = place_or_merge_table_main_order(
            self.session,
            [self._cart_item(self.dish_b, 1)],
            self.seller.username,
            Decimal('0'),
            'dine_in',
            create_order_fn=_create,
        )
        self.assertEqual(action, 'created')
        self.assertIsNotNone(order)
        self.assertEqual(
            BuyOrder.objects.filter(
                seller_id=self.seller.username,
                table_session=self.session,
                payment_status='pending_payment',
            ).count(),
            1,
        )

    def test_place_or_merge_prefers_merge_over_create(self):
        seen = {'created': 0}

        def _create():
            seen['created'] += 1
            return BuyOrder.objects.create(
                buyer_id='buyer_y',
                seller_id=self.seller.username,
                total_amount=Decimal('15.00'),
                subtotal_amount=Decimal('15.00'),
                delivery_fee=Decimal('0'),
                dish_items=[],
                payment_status='pending_payment',
                order_status='created',
                fulfillment_type='dine_in',
                delivery_address='堂食',
                distance_km=Decimal('0'),
                table_session=self.session,
                order_kind='table_main',
            )

        action, order = place_or_merge_table_main_order(
            self.session,
            [self._cart_item(self.dish_b, 1)],
            self.seller.username,
            Decimal('0'),
            'dine_in',
            create_order_fn=_create,
        )
        self.assertEqual(action, 'merged')
        self.assertEqual(seen['created'], 0)
        self.assertEqual(order.order_id, self.pending_order.order_id)
        order.refresh_from_db()
        self.assertEqual(len(order.dish_items), 2)
