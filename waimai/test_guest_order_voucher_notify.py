# 游客订单凭证邮件（付完 / 现金或货到付款后再发）

from datetime import time
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from waimai.guest_order_voucher_notify_helpers import (
    notify_guest_order_voucher,
    schedule_guest_order_voucher_notify,
)
from waimai.models import BuyOrder
from waimai.operating_helpers import get_operating_settings
from waimai.test_shop_helpers import create_test_shop_bundle


class GuestOrderVoucherNotifyTests(TestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='gvmail_seller',
            password='seller-pass-123',
            shop_code='gvmail',
            shop_name='凭证邮件店',
            with_menu=True,
            with_dish=True,
            dish_name='邮件测菜',
            dish_price=Decimal('10.00'),
        )
        self.seller_id = bundle.seller.username
        self.dish = bundle.dish
        ops = get_operating_settings(self.seller_id)
        ops.business_open = time(0, 0)
        ops.business_close = time(23, 59)
        ops.save()

    def _guest_takeaway_order(
        self,
        *,
        email='',
        payment_status='pending_payment',
        payment_method='',
        order_status='created',
    ):
        return BuyOrder.objects.create(
            buyer_id='',
            seller_id=self.seller_id,
            total_amount=Decimal('10.00'),
            subtotal_amount=Decimal('10.00'),
            delivery_fee=Decimal('0.00'),
            dish_items=[{
                'line_id': 'a',
                'dish_id': self.dish.dish_id.hex,
                'name': self.dish.name,
                'price': 10.0,
                'quantity': 1,
                'price_tier': 'general',
                'prepared_count': 0,
                'served_count': 0,
            }],
            payment_status=payment_status,
            payment_method=payment_method or '',
            order_status=order_status,
            delivery_address='【打包自取】',
            fulfillment_type='takeaway',
            guest_contact_name='王五',
            guest_contact_phone='13700137000',
            guest_contact_email=email,
        )

    @patch('waimai.guest_order_voucher_notify_helpers.is_email_ready', return_value=True)
    @patch('waimai.guest_order_voucher_notify_helpers.send_yecao_mail', return_value=True)
    def test_sends_when_paid(self, mock_send, _ready):
        order = self._guest_takeaway_order(
            email='guest@example.com',
            payment_status='paid',
            payment_method='wechat_simulate',
            order_status='awaiting_prep',
        )
        ok = notify_guest_order_voucher(order)
        self.assertTrue(ok)
        mock_send.assert_called_once()
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs['recipient_list'], ['guest@example.com'])
        self.assertIn('订单凭证', kwargs['subject'])
        self.assertIn('顾客姓名', kwargs['message'])
        self.assertIn('王五', kwargs['message'])

    @patch('waimai.guest_order_voucher_notify_helpers.is_email_ready', return_value=True)
    @patch('waimai.guest_order_voucher_notify_helpers.send_yecao_mail', return_value=True)
    def test_sends_when_cash_selected(self, mock_send, _ready):
        order = self._guest_takeaway_order(
            email='guest@example.com',
            payment_status='pending_payment',
            payment_method='cash',
            order_status='awaiting_prep',
        )
        ok = notify_guest_order_voucher(order)
        self.assertTrue(ok)
        mock_send.assert_called_once()

    @patch('waimai.guest_order_voucher_notify_helpers.send_yecao_mail')
    def test_skips_unpaid_before_method(self, mock_send):
        order = self._guest_takeaway_order(
            email='guest@example.com',
            payment_status='pending_payment',
            payment_method='',
            order_status='created',
        )
        ok = notify_guest_order_voucher(order)
        self.assertFalse(ok)
        mock_send.assert_not_called()

    @patch('waimai.guest_order_voucher_notify_helpers.send_yecao_mail')
    def test_skips_without_email(self, mock_send):
        order = self._guest_takeaway_order(
            email='',
            payment_status='paid',
            payment_method='wechat_simulate',
            order_status='awaiting_prep',
        )
        ok = notify_guest_order_voucher(order)
        self.assertFalse(ok)
        mock_send.assert_not_called()

    @patch('waimai.guest_order_voucher_notify_helpers.is_email_ready', return_value=False)
    @patch('waimai.guest_order_voucher_notify_helpers.send_yecao_mail')
    def test_skips_when_smtp_not_ready(self, mock_send, _ready):
        order = self._guest_takeaway_order(
            email='guest@example.com',
            payment_status='paid',
            payment_method='wechat_simulate',
            order_status='awaiting_prep',
        )
        ok = notify_guest_order_voucher(order)
        self.assertFalse(ok)
        mock_send.assert_not_called()

    @patch('waimai.guest_order_voucher_notify_helpers.notify_guest_order_voucher')
    def test_schedule_runs_after_commit(self, mock_notify):
        order = self._guest_takeaway_order(
            email='guest@example.com',
            payment_status='paid',
            order_status='awaiting_prep',
        )
        with self.captureOnCommitCallbacks(execute=True):
            schedule_guest_order_voucher_notify(order)
        mock_notify.assert_called_once()
        self.assertEqual(mock_notify.call_args.args[0].order_id, order.order_id)
