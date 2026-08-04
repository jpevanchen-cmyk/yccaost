# 骑手配送流程 · 取餐 / 开始送餐 / 送达 / 预计时间（进度 82-② · 第三批）

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from waimai.models import BuyOrder, DeliveryOrder, User
from waimai.operating_helpers import get_operating_settings
from waimai.order_timeline_helpers import (
    build_rider_delivery_wait_display,
    build_rider_pickup_wait_display,
    compute_wait_display,
)
from waimai.plugins.fulfillment.delivery_workflow_helpers import (
    apply_rider_complete_delivery,
    apply_rider_pickup,
    apply_rider_start_delivery,
    sync_delivery_overtime,
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

    def test_active_order_count_includes_overtime(self):
        """超时未送达仍算骑手手头未完成单。"""
        from waimai.plugins.fulfillment.dispatch_helpers import count_rider_active_orders

        self._delivery_order(delivery_status='overtime', order_status='delivering')
        self.assertEqual(count_rider_active_orders(self.rider.username), 1)

    def test_waiter_board_hides_overtime_delivery(self):
        """超时未送达的外卖单不再出现在服务员看板。"""
        from waimai.waiter_helpers import query_waiter_active_orders

        order = BuyOrder.objects.create(
            buyer_id='buyer_ot',
            seller_id=self.seller.username,
            total_amount=Decimal('20.00'),
            dish_items=[{'name': '测试菜', 'quantity': 1, 'price': 20.0}],
            payment_status='paid',
            order_status='delivering',
            fulfillment_type='delivery',
            delivery_address='测试地址',
        )
        DeliveryOrder.objects.create(
            buy_order=order,
            rider_id=self.rider.username,
            delivery_fee=Decimal('2.00'),
            distance_km=Decimal('1.0'),
            pickup_address='店里',
            delivery_address='测试地址',
            delivery_status='overtime',
        )
        self.assertNotIn(order.pk, query_waiter_active_orders(self.seller.username).values_list('pk', flat=True))

    def test_start_delivery_sets_estimated_delivery_time(self):
        """开始送餐时写入预计送达（按店铺外卖默认等待分钟）。"""
        settings = get_operating_settings(self.seller.username)
        settings.delivery_default_wait_minutes = 25
        settings.save(update_fields=['delivery_default_wait_minutes'])

        delivery = self._delivery_order(delivery_status='picked_up', order_status='awaiting_delivery')
        before = timezone.now()
        ok, _ = apply_rider_start_delivery(delivery)
        self.assertTrue(ok)
        delivery.refresh_from_db()
        self.assertEqual(delivery.delivery_status, 'in_transit')
        self.assertIsNotNone(delivery.estimated_delivery_time)
        delta = delivery.estimated_delivery_time - before
        self.assertGreaterEqual(int(delta.total_seconds()), 24 * 60)
        self.assertLessEqual(int(delta.total_seconds()), 26 * 60)

    def test_sync_delivery_overtime_from_in_transit(self):
        """过了预计送达仍在送 → 配送线记 overtime。"""
        now = timezone.now()
        delivery = self._delivery_order(delivery_status='in_transit', order_status='delivering')
        delivery.in_transit_at = now - timedelta(minutes=40)
        delivery.estimated_delivery_time = now - timedelta(minutes=5)
        delivery.save(update_fields=['in_transit_at', 'estimated_delivery_time'])

        self.assertTrue(sync_delivery_overtime(delivery))
        delivery.refresh_from_db()
        self.assertEqual(delivery.delivery_status, 'overtime')

    def test_compute_wait_display_countdown_and_overdue(self):
        now = timezone.now()
        future = compute_wait_display(now + timedelta(minutes=10), now=now)
        self.assertFalse(future['is_overdue'])
        self.assertIn('还剩', future['text'])
        self.assertEqual(future['css_class'], 'wait-countdown')

        past = compute_wait_display(now - timedelta(minutes=3), now=now)
        self.assertTrue(past['is_overdue'])
        self.assertIn('已超时', past['text'])
        self.assertEqual(past['css_class'], 'wait-overdue')

    def test_rider_pickup_and_delivery_wait_displays(self):
        now = timezone.now()
        delivery = self._delivery_order()
        delivery.buy_order.estimated_ready_at = now + timedelta(minutes=8)
        delivery.buy_order.save(update_fields=['estimated_ready_at'])

        pickup = build_rider_pickup_wait_display(delivery, now=now)
        self.assertEqual(pickup['label'], '预计取餐')
        self.assertIn('还剩', pickup['text'])

        delivery.delivery_status = 'picked_up'
        self.assertIsNone(build_rider_pickup_wait_display(delivery, now=now))

        delivery.delivery_status = 'in_transit'
        delivery.estimated_delivery_time = now + timedelta(minutes=20)
        delivery.save(update_fields=['delivery_status', 'estimated_delivery_time'])
        delivery.buy_order.refresh_from_db()

        delivery_disp = build_rider_delivery_wait_display(delivery, now=now)
        self.assertEqual(delivery_disp['label'], '预计送达')
        self.assertIn('还剩', delivery_disp['text'])
