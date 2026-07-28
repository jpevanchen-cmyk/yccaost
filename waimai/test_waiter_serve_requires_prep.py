# 服务员交付须后厨先备好

from datetime import time
from decimal import Decimal

from django.test import TestCase

from waimai.models import BuyOrder, ShopProfile, User
from waimai.operating_helpers import get_operating_settings
from waimai.waiter_helpers import (
    mark_all_dish_served,
    mark_dish_unit_served,
    waiter_can_mark_all_served,
)


def _dish_items(*, prepared=0, served=0):
    return [{
        'line_id': 'line-1',
        'dish_id': 'dish-1',
        'name': '试验商品',
        'price': 20,
        'quantity': 1,
        'prepared_count': prepared,
        'served_count': served,
    }]


class WaiterServeRequiresPrepTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='serve_seller', password='seller-pass-123', role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='交付试验店',
            shop_code='srvshop',
            address='试验地址',
        )
        settings = get_operating_settings(self.seller.username)
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=['business_open', 'business_close'])

    def _order(self, **overrides):
        values = {
            'buyer_id': 'buyer1',
            'seller_id': self.seller.username,
            'total_amount': Decimal('20.00'),
            'subtotal_amount': Decimal('20.00'),
            'dish_items': _dish_items(),
            'fulfillment_type': 'takeaway',
            'payment_status': 'paid',
            'payment_method': 'cash',
            'order_status': 'preparing',
        }
        values.update(overrides)
        return BuyOrder.objects.create(**values)

    def test_cannot_serve_before_kitchen_prepares(self):
        order = self._order(dish_items=_dish_items(prepared=0, served=0))
        ok, msg = mark_dish_unit_served(order, 'dish-1', operator_username='waiter1')
        self.assertFalse(ok)
        self.assertIn('备好', msg)
        order.refresh_from_db()
        self.assertEqual(order.dish_items[0]['served_count'], 0)

    def test_can_serve_after_kitchen_prepares(self):
        order = self._order(dish_items=_dish_items(prepared=1, served=0))
        ok, msg = mark_dish_unit_served(order, 'dish-1', operator_username='waiter1')
        self.assertTrue(ok)
        order.refresh_from_db()
        self.assertEqual(order.dish_items[0]['served_count'], 1)

    def test_mark_all_only_serves_prepared_units(self):
        order = self._order(dish_items=_dish_items(prepared=0, served=0))
        self.assertFalse(waiter_can_mark_all_served(order))
        ok, msg = mark_all_dish_served(order, operator_username='waiter1')
        self.assertFalse(ok)
        self.assertIn('备好', msg)

        order.dish_items = _dish_items(prepared=1, served=0)
        order.save(update_fields=['dish_items', 'updated_at'])
        self.assertTrue(waiter_can_mark_all_served(order))
        ok, msg = mark_all_dish_served(order, operator_username='waiter1')
        self.assertTrue(ok)
        order.refresh_from_db()
        self.assertEqual(order.dish_items[0]['served_count'], 1)

    def test_dine_in_same_rule(self):
        order = self._order(fulfillment_type='dine_in', dish_items=_dish_items(prepared=0, served=0))
        ok, msg = mark_dish_unit_served(order, 'dish-1', operator_username='waiter1')
        self.assertFalse(ok)
        self.assertIn('交付', msg)
