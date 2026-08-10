# 入金申请邮件双轨 + 发起后通知

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from .time_helpers import now_local_wall

from waimai.models import BuyOrder, CashRemittanceRequest, User
from waimai.operating_helpers import get_operating_settings
from waimai.remittance_notify_helpers import (
    _collect_remittance_notify_recipients,
    notify_remittance_request,
)


class RemittanceNotifyTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='remit_mail_seller',
            password='x',
            role='seller',
        )

    def test_collect_boss_and_duty_dedupe(self):
        op = get_operating_settings(self.seller.username)
        op.boss_remittance_notify_enabled = True
        op.boss_remittance_notify_email = 'a@test.com, b@test.com'
        op.duty_remittance_notify_enabled = True
        op.duty_remittance_notify_email = 'b@test.com, c@test.com'
        op.save()
        recipients = _collect_remittance_notify_recipients(op)
        self.assertEqual(recipients, ['a@test.com', 'b@test.com', 'c@test.com'])

    @patch('waimai.remittance_notify_helpers.send_yecao_mail')
    @patch('waimai.email_helpers.is_email_ready', return_value=True)
    def test_notify_sends_both_tracks(self, _ready, send_mail):
        op = get_operating_settings(self.seller.username)
        op.boss_remittance_notify_enabled = True
        op.boss_remittance_notify_email = 'boss@test.com'
        op.duty_remittance_notify_enabled = True
        op.duty_remittance_notify_email = 'duty@test.com'
        op.save()
        remit = CashRemittanceRequest.objects.create(
            seller_id=self.seller.username,
            rider_id='rider1',
            total_amount=Decimal('50'),
            order_count=2,
            status='pending',
        )
        notify_remittance_request(remit)
        send_mail.assert_called_once()
        self.assertEqual(
            send_mail.call_args.kwargs['recipient_list'],
            ['boss@test.com', 'duty@test.com'],
        )

    @patch('waimai.remittance_notify_helpers.maybe_notify_remittance_request')
    def test_create_request_schedules_notify(self, notify_fn):
        from waimai.rider_cash_helpers import create_cash_remittance_request

        BuyOrder.objects.create(
            buyer_id='buyer_x',
            seller_id=self.seller.username,
            total_amount=Decimal('25'),
            subtotal_amount=Decimal('25'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            cash_collected_at=now_local_wall(),
            cash_collected_by='rider1',
            cash_collected_amount=Decimal('25'),
        )
        req, msg = create_cash_remittance_request(self.seller.username, 'rider1')
        self.assertIsNotNone(req)
        notify_fn.assert_called_once_with(req)
