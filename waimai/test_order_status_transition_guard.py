# 订单主状态守门员 · 观察模式测试（进度 82 第一步）

from django.test import SimpleTestCase
from types import SimpleNamespace

from .order_status_transition_helpers import (
    GUARD_MODE_ENFORCE,
    GUARD_MODE_OBSERVE,
    check_order_status_transition,
    transition_order_status,
)


def _order(**kwargs):
    defaults = {
        'order_id': '00000000-0000-0000-0000-000000000001',
        'fulfillment_type': 'delivery',
        'order_status': 'ready_pickup',
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class OrderStatusTransitionGuardTests(SimpleTestCase):
    def test_delivery_pickup_to_delivering_is_violation(self):
        order = _order(order_status='ready_pickup', fulfillment_type='delivery')
        ok, codes = check_order_status_transition(
            order, 'ready_pickup', 'delivering', source='test',
        )
        self.assertFalse(ok)
        self.assertIn('delivery_pickup_should_be_awaiting_delivery', codes)

    def test_observe_mode_still_writes_on_violation(self):
        order = _order(order_status='ready_pickup', fulfillment_type='delivery')
        ok, codes = transition_order_status(
            order, 'delivering', source='test.pickup', mode=GUARD_MODE_OBSERVE,
        )
        self.assertFalse(ok)
        self.assertIn('delivery_pickup_should_be_awaiting_delivery', codes.split(','))
        self.assertEqual(order.order_status, 'delivering')

    def test_enforce_mode_blocks_violation(self):
        order = _order(order_status='ready_pickup', fulfillment_type='delivery')
        ok, _ = transition_order_status(
            order, 'delivering', source='test.pickup', mode=GUARD_MODE_ENFORCE,
        )
        self.assertFalse(ok)
        self.assertEqual(order.order_status, 'ready_pickup')

    def test_awaiting_prep_to_preparing_ok(self):
        order = _order(order_status='awaiting_prep', fulfillment_type='takeaway')
        ok, codes = check_order_status_transition(
            order, 'awaiting_prep', 'preparing', source='test',
        )
        self.assertTrue(ok)
        self.assertEqual(codes, [])

    def test_ready_pickup_to_awaiting_delivery_ok_for_delivery(self):
        order = _order(order_status='ready_pickup', fulfillment_type='delivery')
        ok, codes = check_order_status_transition(
            order, 'ready_pickup', 'awaiting_delivery', source='test',
        )
        self.assertTrue(ok)
        self.assertEqual(codes, [])

    def test_deprecated_status_write_flagged(self):
        order = _order(order_status='created', fulfillment_type='order')
        ok, codes = check_order_status_transition(
            order, 'created', 'awaiting_payment', source='test',
        )
        self.assertFalse(ok)
        self.assertIn('deprecated_status_write', codes)
