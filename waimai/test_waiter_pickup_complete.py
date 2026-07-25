# 服务员台：打包/堂食「客人已取走」与无法收款提示

from datetime import time
from decimal import Decimal

from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase

from waimai.models import BuyOrder, ShopProfile, User
from waimai.operating_helpers import get_operating_settings
from waimai.shop_work_helpers import build_waiter_board_context
from waimai.waiter_handlers import handle_waiter_post
from waimai.waiter_helpers import (
    sync_waiter_service_status,
    waiter_can_close_uncollected,
    waiter_can_complete_in_store,
)


def _served_dish_items():
    return [{
        'line_id': 'line-1',
        'dish_id': 'dish-1',
        'name': '试验商品',
        'price': 20,
        'quantity': 1,
        'served_count': 1,
        'prepared_count': 1,
    }]


class WaiterPickupCompleteTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='pickup_seller', password='seller-pass-123', role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='取走试验店',
            shop_code='pickshop',
            address='试验地址',
        )
        settings = get_operating_settings(self.seller.username)
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=['business_open', 'business_close'])
        self.factory = RequestFactory()

    def _make_takeaway_order(self, **overrides):
        values = {
            'buyer_id': 'pickup_buyer',
            'seller_id': self.seller.username,
            'total_amount': Decimal('20.00'),
            'subtotal_amount': Decimal('20.00'),
            'dish_items': _served_dish_items(),
            'fulfillment_type': 'takeaway',
            'payment_status': 'pending_payment',
            'payment_method': 'cash',
            'order_status': 'preparing',
        }
        values.update(overrides)
        return BuyOrder.objects.create(**values)

    def _post_complete_pickup(self, order):
        request = self.factory.post('/', {
            'complete_pickup': '1',
            'order_id': str(order.order_id),
        })
        request.user = self.seller
        request.shop_work_user = self.seller
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()
        setattr(request, '_messages', FallbackStorage(request))
        response = handle_waiter_post(
            request,
            self.seller.username,
            redirect_to='/work/',
        )
        return response, request

    def test_paid_wechat_does_not_show_uncollected_block(self):
        order = self._make_takeaway_order(
            payment_method='wechat_simulate',
            payment_status='paid',
            order_status='ready_pickup',
        )
        self.assertFalse(waiter_can_close_uncollected(order))
        row = build_waiter_board_context(self.seller.username)['orders'][0]
        self.assertFalse(row['can_close_uncollected'])
        self.assertTrue(row['can_complete_in_store'])

    def test_sync_sets_ready_pickup_when_all_served_but_unpaid(self):
        order = self._make_takeaway_order(order_status='preparing')
        fields = sync_waiter_service_status(order)
        order.save(update_fields=list(dict.fromkeys(fields)))
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'ready_pickup')
        self.assertTrue(waiter_can_close_uncollected(order))
        self.assertFalse(waiter_can_complete_in_store(order))

    def test_complete_pickup_auto_finishes_paid_order_stuck_in_preparing(self):
        order = self._make_takeaway_order(
            payment_method='wechat_simulate',
            payment_status='paid',
            order_status='preparing',
        )
        self.assertTrue(waiter_can_complete_in_store(order))
        response, request = self._post_complete_pickup(order)
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'completed')
        msgs = [str(m) for m in get_messages(request)]
        self.assertTrue(any('已完成' in msg for msg in msgs))

    def test_complete_pickup_works_from_ready_pickup(self):
        order = self._make_takeaway_order(
            payment_method='wechat_simulate',
            payment_status='paid',
            order_status='ready_pickup',
        )
        response, request = self._post_complete_pickup(order)
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'completed')

    def test_basic_order_shows_complete_button_when_all_delivered_and_paid(self):
        order = BuyOrder.objects.create(
            buyer_id='pickup_buyer',
            seller_id=self.seller.username,
            total_amount=Decimal('81.20'),
            subtotal_amount=Decimal('81.20'),
            dish_items=[
                {
                    'line_id': 'line-a',
                    'dish_id': 'dish-a',
                    'name': '回锅肉',
                    'price': 30,
                    'quantity': 2,
                    'served_count': 2,
                    'prepared_count': 2,
                },
                {
                    'line_id': 'line-b',
                    'dish_id': 'dish-b',
                    'name': '宫保鸡丁',
                    'price': 21.2,
                    'quantity': 1,
                    'served_count': 1,
                    'prepared_count': 1,
                },
            ],
            fulfillment_type='order',
            payment_method='wechat_simulate',
            payment_status='paid',
            order_status='preparing',
        )
        self.assertTrue(waiter_can_complete_in_store(order))
        row = build_waiter_board_context(self.seller.username)['orders'][0]
        self.assertTrue(row['can_complete_in_store'])

    def test_basic_order_complete_pickup_finishes_order(self):
        order = BuyOrder.objects.create(
            buyer_id='pickup_buyer',
            seller_id=self.seller.username,
            total_amount=Decimal('20.00'),
            subtotal_amount=Decimal('20.00'),
            dish_items=_served_dish_items(),
            fulfillment_type='order',
            payment_method='wechat_simulate',
            payment_status='paid',
            order_status='preparing',
        )
        response, request = self._post_complete_pickup(order)
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'completed')
        msgs = [str(m) for m in get_messages(request)]
        self.assertTrue(any('已完成' in msg for msg in msgs))
