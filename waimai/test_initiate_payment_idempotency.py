# 幂等第 7 步：选支付方式 initiate_payment 防连点

from datetime import time
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from waimai.models import BuyOrder, MenuProfileItem, User
from waimai.operating_helpers import get_operating_settings
from waimai.payments.core import get_payment_settings
from waimai.shop_work_auth import establish_shop_work_session
from waimai.staff_account_helpers import PERM_DINING_WAITER, staff_internal_username
from waimai.test_shop_helpers import create_test_shop_bundle


class InitiatePaymentIdempotencyTests(TestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='pay_idem_seller',
            password='seller-pass-123',
            shop_code='payidem',
            shop_name='支付幂等试验店',
            with_menu=True,
            with_dish=True,
            dish_name='支付幂等试验菜',
            dish_price=Decimal('15.00'),
        )
        self.seller = bundle.seller
        self.dish = bundle.dish
        self.buyer = User.objects.create_user(
            username='pay_idem_buyer', password='buyer-pass-123', role='buyer',
        )
        settings = get_operating_settings(self.seller.username)
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.takeaway_channel_enabled = True
        settings.save(update_fields=[
            'business_open', 'business_close', 'takeaway_channel_enabled',
        ])
        pay = get_payment_settings(self.seller.username)
        pay.enable_cash = True
        pay.enable_simulate = True
        pay.save(update_fields=['enable_cash', 'enable_simulate'])

        MenuProfileItem.objects.filter(
            profile=bundle.profile, dish=self.dish,
        ).update(sales_cap=5, sold_count=0)
        self.menu_item = MenuProfileItem.objects.get(profile=bundle.profile, dish=self.dish)

        self.waiter = User.objects.create_user(
            username=staff_internal_username(self.seller.username, '服务员A'),
            password='waiter-pass-123',
            role='staff',
            employer_seller_id=self.seller.username,
            staff_account_type='employee',
            staff_job_title='服务员',
            staff_permissions=[PERM_DINING_WAITER],
        )

    def _make_pending_order(self) -> BuyOrder:
        return BuyOrder.objects.create(
            buyer_id=self.buyer.username,
            seller_id=self.seller.username,
            total_amount=Decimal('15.00'),
            subtotal_amount=Decimal('15.00'),
            dish_items=[{
                'line_id': 'line1',
                'dish_id': self.dish.dish_id.hex,
                'name': self.dish.name,
                'price': 15.0,
                'quantity': 1,
                'price_tier': 'general',
            }],
            payment_status='pending_payment',
            order_status='awaiting_payment',
            fulfillment_type='takeaway',
        )

    def _pay_payload(self, method: str, key: str = ''):
        data = {'payment_method': method}
        if key:
            data['idempotency_key'] = key
        return data

    def test_same_key_cash_select_applies_catalog_once(self):
        order = self._make_pending_order()
        client = Client()
        client.login(username=self.buyer.username, password='buyer-pass-123')
        url = reverse('pay_order', kwargs={'order_id': order.order_id})
        key = 'pay-cash-key-00000001'
        payload = self._pay_payload('cash', key)

        resp1 = client.post(url, payload)
        resp2 = client.post(url, payload)

        self.assertEqual(resp1.status_code, 302)
        self.assertEqual(resp2.status_code, 302)
        self.assertEqual(resp1['Location'], resp2['Location'])
        self.menu_item.refresh_from_db()
        self.assertEqual(self.menu_item.sold_count, 1)
        order.refresh_from_db()
        self.assertEqual(order.payment_method, 'cash')
        self.assertEqual(order.order_status, 'awaiting_prep')
        self.assertTrue(order.catalog_sales_applied)

    def test_same_key_simulate_paid_once(self):
        order = self._make_pending_order()
        client = Client()
        client.login(username=self.buyer.username, password='buyer-pass-123')
        url = reverse('pay_order', kwargs={'order_id': order.order_id})
        key = 'pay-sim-key-000000001'
        payload = self._pay_payload('wechat_simulate', key)

        resp1 = client.post(url, payload)
        resp2 = client.post(url, payload)

        self.assertEqual(resp1.status_code, 302)
        self.assertEqual(resp2.status_code, 302)
        self.assertEqual(resp1['Location'], resp2['Location'])
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'paid')
        self.menu_item.refresh_from_db()
        self.assertEqual(self.menu_item.sold_count, 0)

    def test_waiter_same_key_cash_select_once(self):
        order = self._make_pending_order()
        client = Client()
        session = client.session
        establish_shop_work_session(
            type('Req', (), {'session': session})(),
            self.waiter,
            seller_id=self.seller.username,
            shop_code='payidem',
        )
        session.save()
        url = reverse('waiter_pay_order', kwargs={'order_id': order.order_id})
        key = 'waiter-pay-key-0000001'
        payload = self._pay_payload('cash', key)

        resp1 = client.post(url, payload)
        resp2 = client.post(url, payload)

        self.assertEqual(resp1.status_code, 302)
        self.assertEqual(resp2.status_code, 302)
        self.assertEqual(resp1['Location'], resp2['Location'])
        self.menu_item.refresh_from_db()
        self.assertEqual(self.menu_item.sold_count, 1)
        order.refresh_from_db()
        self.assertEqual(order.payment_method, 'cash')
        self.assertEqual(order.order_status, 'awaiting_prep')
