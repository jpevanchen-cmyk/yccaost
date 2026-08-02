# 订单主状态事件表测试（进度 82-③）

from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from waimai.models import BuyOrder
from waimai.order_status_event_helpers import (
    EVENT_DELIVERY_COMPLETED,
    EVENT_GOODS_FULLY_DELIVERED,
    EVENT_MANUAL_COMPLETE,
    EVENT_PAYMENT_RECEIVED,
    EVENT_PAYMENT_UNCOLLECTED_CLOSE,
    handle_order_status_event,
    try_complete_order,
)


def _served_items():
    return [{
        'line_id': 'line-1',
        'dish_id': 'dish-1',
        'name': '试验商品',
        'price': 20,
        'quantity': 1,
        'served_count': 1,
        'prepared_count': 1,
    }]


class OrderStatusEventUnitTests(SimpleTestCase):
    def test_payment_received_moves_created_to_awaiting_prep(self):
        order = SimpleNamespace(
            order_status='created',
            payment_status='paid',
            fulfillment_type='takeaway',
            dish_items=[],
            cash_shortfall_status='',
        )
        order.cash_exception_unresolved = lambda: False
        order.cash_shortfall_waiting_buyer = lambda: False
        order.is_dine_in = lambda: False
        order.is_basic_order = lambda: False
        order.is_in_store = lambda: True

        fields = handle_order_status_event(
            order,
            EVENT_PAYMENT_RECEIVED,
            source='test.payment',
        )
        self.assertEqual(order.order_status, 'awaiting_prep')
        self.assertIn('order_status', fields)

    def test_goods_delivered_completes_when_paid(self):
        order = SimpleNamespace(
            order_status='preparing',
            payment_status='paid',
            fulfillment_type='takeaway',
            dish_items=_served_items(),
            cash_shortfall_status='',
        )
        order.is_in_store = lambda: True
        order.is_basic_order = lambda: False
        order.is_dine_in = lambda: False
        order.fulfillment_type = 'takeaway'
        order.cash_exception_unresolved = lambda: False
        order.cash_shortfall_waiting_buyer = lambda: False

        handle_order_status_event(
            order,
            EVENT_GOODS_FULLY_DELIVERED,
            source='test.goods',
        )
        self.assertEqual(order.order_status, 'completed')

    def test_delivery_completed_requires_paid(self):
        order = SimpleNamespace(
            order_status='delivering',
            payment_status='pending_payment',
            fulfillment_type='delivery',
            dish_items=[],
            cash_shortfall_status='',
        )
        order.cash_exception_unresolved = lambda: False
        order.cash_shortfall_waiting_buyer = lambda: False
        order.is_dine_in = lambda: False

        fields = try_complete_order(
            order,
            source='test.delivery',
            delivery_confirmed=True,
        )
        self.assertEqual(fields, [])
        self.assertEqual(order.order_status, 'delivering')

    def test_manual_complete_from_ready_pickup(self):
        order = SimpleNamespace(
            order_status='ready_pickup',
            payment_status='paid',
            fulfillment_type='takeaway',
            dish_items=_served_items(),
            cash_shortfall_status='',
        )
        order.is_in_store = lambda: True
        order.is_basic_order = lambda: False
        order.cash_exception_unresolved = lambda: False
        order.cash_shortfall_waiting_buyer = lambda: False
        order.is_dine_in = lambda: False

        handle_order_status_event(
            order,
            EVENT_MANUAL_COMPLETE,
            source='test.manual',
        )
        self.assertEqual(order.order_status, 'completed')


class OrderStatusEventIntegrationTests(TestCase):
    def test_sync_waiter_completes_paid_takeaway_via_event(self):
        order = BuyOrder.objects.create(
            buyer_id='evt_buyer',
            seller_id='evt_seller',
            total_amount=Decimal('20.00'),
            subtotal_amount=Decimal('20.00'),
            dish_items=_served_items(),
            fulfillment_type='takeaway',
            payment_method='wechat_simulate',
            payment_status='paid',
            order_status='preparing',
        )
        from waimai.waiter_helpers import sync_waiter_service_status

        fields = sync_waiter_service_status(order)
        order.save(update_fields=list(dict.fromkeys(fields)))
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'completed')

    def test_uncollected_close_from_ready_pickup(self):
        order = BuyOrder.objects.create(
            buyer_id='evt_buyer2',
            seller_id='evt_seller2',
            total_amount=Decimal('20.00'),
            subtotal_amount=Decimal('20.00'),
            dish_items=_served_items(),
            fulfillment_type='takeaway',
            payment_method='cash',
            payment_status='pending_payment',
            order_status='ready_pickup',
        )
        order.payment_status = 'uncollected'
        fields = handle_order_status_event(
            order,
            EVENT_PAYMENT_UNCOLLECTED_CLOSE,
            source='test.uncollected',
        )
        order.save(update_fields=list(dict.fromkeys(['payment_status', *fields])))
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'completed')
