# 进度 85：堂食禁自动翻台、客人时间线、买家双标签、历程去重

from decimal import Decimal
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from waimai.dine_models import ShopTable, TableSession
from waimai.models import BuyOrder, ShopProfile, User
from waimai.order_status_event_helpers import (
    EVENT_GOODS_FULLY_DELIVERED,
    EVENT_MANUAL_COMPLETE,
    handle_order_status_event,
)
from waimai.order_timeline_helpers import build_order_timeline
from waimai.waiter_helpers import sync_waiter_service_status


def _served_items(qty=1):
    return [{
        'line_id': 'line-1',
        'dish_id': 'dish-1',
        'name': '试验商品',
        'price': 20,
        'quantity': qty,
        'served_count': qty,
        'prepared_count': qty,
    }]


def _three_dish_items():
    return [
        {
            'line_id': f'line-{i}',
            'dish_id': f'dish-{i}',
            'name': f'菜{i}',
            'price': 10,
            'quantity': 1,
            'served_count': 1,
            'prepared_count': 1,
        }
        for i in range(1, 4)
    ]


class Progress85UnitTests(SimpleTestCase):
    def test_dine_in_goods_delivered_does_not_auto_complete(self):
        order = SimpleNamespace(
            order_status='preparing',
            payment_status='paid',
            fulfillment_type='dine_in',
            dish_items=_served_items(),
            cash_shortfall_status='',
        )
        order.is_dine_in = lambda: True
        order.is_in_store = lambda: True
        order.is_basic_order = lambda: False
        order.cash_exception_unresolved = lambda: False
        order.cash_shortfall_waiting_buyer = lambda: False

        handle_order_status_event(
            order,
            EVENT_GOODS_FULLY_DELIVERED,
            source='test.dine_in',
        )
        self.assertNotEqual(order.order_status, 'completed')

    def test_takeaway_goods_delivered_still_auto_completes(self):
        order = SimpleNamespace(
            order_status='preparing',
            payment_status='paid',
            fulfillment_type='takeaway',
            dish_items=_served_items(),
            cash_shortfall_status='',
        )
        order.is_dine_in = lambda: False
        order.is_in_store = lambda: True
        order.is_basic_order = lambda: False
        order.cash_exception_unresolved = lambda: False
        order.cash_shortfall_waiting_buyer = lambda: False

        handle_order_status_event(
            order,
            EVENT_GOODS_FULLY_DELIVERED,
            source='test.takeaway',
        )
        self.assertEqual(order.order_status, 'completed')


class Progress85IntegrationTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='p85_seller', password='x', role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='85试验店',
            shop_code='p85shop',
            address='测试路',
        )

    def test_dine_in_sync_does_not_complete_paid_order(self):
        order = BuyOrder.objects.create(
            buyer_id='p85_buyer',
            seller_id=self.seller.username,
            total_amount=Decimal('20.00'),
            subtotal_amount=Decimal('20.00'),
            dish_items=_served_items(),
            fulfillment_type='dine_in',
            payment_method='wechat_simulate',
            payment_status='paid',
            order_status='preparing',
        )
        fields = sync_waiter_service_status(order)
        order.save(update_fields=list(dict.fromkeys(fields)))
        order.refresh_from_db()
        self.assertNotEqual(order.order_status, 'completed')

    def test_dine_in_manual_complete_closes_table_session(self):
        table = ShopTable.objects.create(
            seller_id=self.seller.username,
            table_number='007',
            is_active=True,
        )
        session = TableSession.objects.create(
            seller_id=self.seller.username,
            shop_table=table,
            session_type='main',
            status='open',
        )
        order = BuyOrder.objects.create(
            buyer_id='',
            seller_id=self.seller.username,
            total_amount=Decimal('20.00'),
            subtotal_amount=Decimal('20.00'),
            dish_items=_served_items(),
            fulfillment_type='dine_in',
            payment_method='cash',
            payment_status='paid',
            order_status='ready_pickup',
            table_session=session,
        )
        fields = handle_order_status_event(
            order,
            EVENT_MANUAL_COMPLETE,
            source='test.manual_dine_in',
        )
        order.save(update_fields=list(dict.fromkeys(fields)))
        order.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(order.order_status, 'completed')
        self.assertEqual(session.status, 'closed')

    def test_goods_delivered_timeline_single_from_source_field(self):
        order = BuyOrder.objects.create(
            buyer_id='p85_buyer2',
            seller_id=self.seller.username,
            total_amount=Decimal('60.00'),
            subtotal_amount=Decimal('60.00'),
            dish_items=_three_dish_items(),
            fulfillment_type='takeaway',
            payment_method='wechat_simulate',
            payment_status='paid',
            order_status='preparing',
        )
        for _ in range(3):
            fields = sync_waiter_service_status(order)
            if fields:
                order.save(update_fields=list(dict.fromkeys(fields)))
            order.refresh_from_db()
        labels = [lbl for lbl, _ in build_order_timeline(order, viewer='work')]
        self.assertEqual(labels.count('商品已全部交付'), 1)
        self.assertIsNotNone(order.goods_delivered_at)

    def test_buyer_timeline_hides_goods_delivered(self):
        order = BuyOrder.objects.create(
            buyer_id='p85_buyer3',
            seller_id=self.seller.username,
            total_amount=Decimal('20.00'),
            dish_items=[],
            fulfillment_type='takeaway',
            payment_status='paid',
            order_status='preparing',
            goods_delivered_at=timezone.now(),
        )
        labels = [lbl for lbl, _ in build_order_timeline(order, viewer='buyer')]
        self.assertNotIn('商品已全部交付', labels)
        work_labels = [lbl for lbl, _ in build_order_timeline(order, viewer='work')]
        self.assertIn('商品已全部交付', work_labels)

    def test_buyer_dine_in_ready_shows_can_start_eating(self):
        now = timezone.now()
        order = BuyOrder.objects.create(
            buyer_id='p85_buyer4',
            seller_id=self.seller.username,
            total_amount=Decimal('20.00'),
            dish_items=[],
            fulfillment_type='dine_in',
            payment_status='paid',
            order_status='ready_pickup',
            ready_at=now,
        )
        labels = [lbl for lbl, _ in build_order_timeline(order, viewer='buyer')]
        self.assertIn('就餐中', labels)
        self.assertNotIn('已出餐', labels)

    def test_order_history_shows_dual_tags_not_awaiting_cash(self):
        order = BuyOrder.objects.create(
            buyer_id='hist_buyer',
            seller_id=self.seller.username,
            total_amount=Decimal('30.00'),
            dish_items=[],
            fulfillment_type='takeaway',
            payment_method='cash',
            payment_status='pending_payment',
            order_status='preparing',
        )
        html = render_to_string('waimai/order_history.html', {
            'order_rows': [{
                'order': order,
                'shop_name': '85试验店',
                'unread_msg_count': 0,
            }],
        })
        self.assertIn('待支付', html)
        self.assertIn('现金', html)
        self.assertNotIn('待确认现金', html)
