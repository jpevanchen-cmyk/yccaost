# 骑手配送流程 · 取餐 / 开始送餐 / 送达（进度 82-②）

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from waimai.models import BuyOrder, DeliveryOrder, User
from waimai.plugins.fulfillment.delivery_workflow_helpers import (
    apply_rider_complete_delivery,
    apply_rider_pickup,
    apply_rider_start_delivery,
)
from waimai.staff_account_helpers import PERM_DINING_RIDER, STAFF_WORK_ON_DUTY


class DeliveryWorkflowTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='dw_seller', password='pass-12345', role='seller',
        )
        self.rider = User.objects.create_user(
            username='dw_rider',
            password='pass-12345',
            role='staff',
            employer_seller_id=self.seller.username,
            staff_permissions=[PERM_DINING_RIDER],
            staff_work_status=STAFF_WORK_ON_DUTY,
        )

    def _delivery_order(self, *, delivery_status='accepted', order_status='ready_pickup'):
        order = BuyOrder.objects.create(
            buyer_id='buyer1',
            seller_id=self.seller.username,
            total_amount=Decimal('20.00'),
            dish_items=[{
                'name': '测试菜', 'quantity': 1, 'price': 20.0,
                'served_count': 1, 'prepared_count': 1,
            }],
            payment_status='paid',
            order_status=order_status,
            fulfillment_type='delivery',
            delivery_address='测试地址',
        )
        delivery = DeliveryOrder.objects.create(
            buy_order=order,
            rider_id=self.rider.username,
            delivery_fee=Decimal('2.00'),
            distance_km=Decimal('1.0'),
            pickup_address='店里',
            delivery_address='测试地址',
            delivery_status=delivery_status,
        )
        return delivery

    def test_pickup_sets_awaiting_delivery_not_delivering(self):
        delivery = self._delivery_order()
        ok, _ = apply_rider_pickup(delivery)
        self.assertTrue(ok)
        delivery.buy_order.refresh_from_db()
        delivery.refresh_from_db()
        self.assertEqual(delivery.delivery_status, 'picked_up')
        self.assertEqual(delivery.buy_order.order_status, 'awaiting_delivery')

    def test_complete_requires_start_delivery(self):
        delivery = self._delivery_order(delivery_status='picked_up', order_status='awaiting_delivery')
        ok, msg = apply_rider_complete_delivery(delivery)
        self.assertFalse(ok)
        self.assertIn('开始送餐', msg)

    def test_start_then_complete(self):
        delivery = self._delivery_order(delivery_status='picked_up', order_status='awaiting_delivery')
        ok, _ = apply_rider_start_delivery(delivery)
        self.assertTrue(ok)
        ok, _ = apply_rider_complete_delivery(delivery)
        self.assertTrue(ok)
        delivery.buy_order.refresh_from_db()
        delivery.refresh_from_db()
        self.assertEqual(delivery.delivery_status, 'completed')
        self.assertEqual(delivery.buy_order.order_status, 'completed')
