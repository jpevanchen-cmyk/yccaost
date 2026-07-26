# H3：双轨新订单邮件

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from waimai.models import BuyOrder, User
from waimai.order_notify_helpers import _collect_order_notify_recipients, notify_new_order
from waimai.operating_helpers import get_operating_settings


class DualOrderNotifyTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='dual_mail_seller',
            password='x',
            role='seller',
        )

    def test_collect_boss_and_duty_dedupe(self):
        op = get_operating_settings(self.seller.username)
        op.boss_order_notify_enabled = True
        op.boss_order_notify_email = 'a@test.com, b@test.com'
        op.duty_order_notify_enabled = True
        op.duty_order_notify_email = 'b@test.com, c@test.com'
        op.save()
        recipients = _collect_order_notify_recipients(op)
        self.assertEqual(recipients, ['a@test.com', 'b@test.com', 'c@test.com'])

    @patch('waimai.order_notify_helpers.send_yecao_mail')
    @patch('waimai.email_helpers.is_email_ready', return_value=True)
    def test_notify_sends_both_tracks(self, _ready, send_mail):
        op = get_operating_settings(self.seller.username)
        op.boss_order_notify_enabled = True
        op.boss_order_notify_email = 'boss@test.com'
        op.duty_order_notify_enabled = True
        op.duty_order_notify_email = 'duty@test.com'
        op.save()
        order = BuyOrder.objects.create(
            buyer_id='buyer_x',
            seller_id=self.seller.username,
            total_amount=Decimal('12'),
            subtotal_amount=Decimal('12'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='awaiting_prep',
            fulfillment_type='takeaway',
        )
        notify_new_order(order)
        send_mail.assert_called_once()
        self.assertEqual(
            send_mail.call_args.kwargs['recipient_list'],
            ['boss@test.com', 'duty@test.com'],
        )
