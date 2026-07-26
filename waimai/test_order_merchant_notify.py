# 试跑补丁 H：商家新单提醒口径（待支付不进提醒）

from decimal import Decimal

from django.test import TestCase

from waimai.models import BuyOrder, Dish, User
from waimai.order_alert_helpers import is_shop_new_order, query_shop_new_orders, shop_new_order_q


class OrderMerchantNotifyTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='notify_seller',
            password='x',
            role='seller',
        )

    def _order(self, **kwargs):
        defaults = {
            'buyer_id': 'buyer_a',
            'seller_id': self.seller.username,
            'total_amount': Decimal('10'),
            'subtotal_amount': Decimal('10'),
            'delivery_fee': Decimal('0'),
            'dish_items': [],
            'payment_status': 'pending_payment',
            'order_status': 'awaiting_payment',
            'fulfillment_type': 'takeaway',
        }
        defaults.update(kwargs)
        return BuyOrder.objects.create(**defaults)

    def test_takeaway_pending_payment_not_new_order(self):
        """打包 · 支付页未选方式：不算新单（开发者实测场景）。"""
        order = self._order()
        self.assertFalse(is_shop_new_order(order))
        self.assertEqual(query_shop_new_orders(self.seller.username).count(), 0)

    def test_paid_awaiting_prep_is_new_order(self):
        order = self._order(payment_status='paid', order_status='awaiting_prep')
        self.assertTrue(is_shop_new_order(order))
        self.assertEqual(query_shop_new_orders(self.seller.username).count(), 1)

    def test_takeaway_cash_before_pay_is_new_order(self):
        order = self._order(
            payment_method='cash',
            order_status='awaiting_prep',
        )
        self.assertTrue(is_shop_new_order(order))

    def test_shop_new_order_q_excludes_unpaid_non_cash(self):
        self._order()
        self._order(fulfillment_type='delivery', order_status='awaiting_payment')
        qs = BuyOrder.objects.filter(seller_id=self.seller.username).filter(shop_new_order_q())
        self.assertEqual(qs.count(), 0)
