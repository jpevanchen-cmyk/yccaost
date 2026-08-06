# 幂等第 5 步：店铺工作台 Panel 防重复推进状态

import json
from datetime import time
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from waimai.models import BuyOrder
from waimai.operating_helpers import get_operating_settings
from waimai.panel_refresh_helpers import PANEL_REQUEST_HEADER
from waimai.shop_work_auth import establish_shop_work_session
from waimai.test_shop_helpers import create_test_shop_bundle


def _dish_items_for_kitchen():
    return [{
        'line_id': 'line-1',
        'dish_id': 'dish-wb-idem',
        'name': '幂等试验菜',
        'price': 10,
        'quantity': 2,
        'prepared_count': 0,
        'served_count': 0,
    }]


class WorkbenchIdempotencyTests(TestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='wb_idem_seller',
            shop_code='wbidem',
            shop_name='工作台幂等店',
        )
        self.seller = bundle.seller
        settings = get_operating_settings(self.seller.username)
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=['business_open', 'business_close'])
        self.order = BuyOrder.objects.create(
            buyer_id='buyer1',
            seller_id=self.seller.username,
            total_amount=Decimal('20.00'),
            dish_items=_dish_items_for_kitchen(),
            payment_status='paid',
            payment_method='wechat_simulate',
            order_status='preparing',
            fulfillment_type='takeaway',
        )
        self.client = Client()
        session = self.client.session
        establish_shop_work_session(
            type('Req', (), {'session': session})(),
            self.seller,
            seller_id=self.seller.username,
            shop_code='wbidem',
        )
        session.save()
        self.work_url = reverse('shop_work', kwargs={'shop_code': 'wbidem'}) + '?view=kitchen'
        self.panel_headers = {'HTTP_X_REQUESTED_WITH': PANEL_REQUEST_HEADER}

    def _prepared_count(self):
        self.order.refresh_from_db()
        return self.order.dish_items[0]['prepared_count']

    def test_same_key_mark_prepared_only_once(self):
        payload = {
            'mark_prepared_unit': '1',
            'order_id': str(self.order.order_id),
            'dish_id': 'dish-wb-idem',
            'idempotency_key': 'wb-prep-key-00000001',
        }
        resp1 = self.client.post(self.work_url, payload, **self.panel_headers)
        resp2 = self.client.post(self.work_url, payload, **self.panel_headers)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp1.content, resp2.content)
        self.assertEqual(self._prepared_count(), 1)

    def test_without_key_two_marks_increment_twice(self):
        payload = {
            'mark_prepared_unit': '1',
            'order_id': str(self.order.order_id),
            'dish_id': 'dish-wb-idem',
        }
        self.client.post(self.work_url, payload, **self.panel_headers)
        self.client.post(self.work_url, payload, **self.panel_headers)
        self.assertEqual(self._prepared_count(), 2)

    def test_same_key_start_preparing_only_once(self):
        pending = BuyOrder.objects.create(
            buyer_id='buyer2',
            seller_id=self.seller.username,
            total_amount=Decimal('15.00'),
            dish_items=_dish_items_for_kitchen(),
            payment_status='paid',
            payment_method='wechat_simulate',
            order_status='awaiting_prep',
            fulfillment_type='takeaway',
        )
        payload = {
            'start_preparing': '1',
            'order_id': str(pending.order_id),
            'idempotency_key': 'wb-start-key-00000001',
        }
        self.client.post(self.work_url, payload, **self.panel_headers)
        self.client.post(self.work_url, payload, **self.panel_headers)
        pending.refresh_from_db()
        self.assertEqual(pending.order_status, 'preparing')
