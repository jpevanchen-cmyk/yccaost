# 待支付超时自动取消（不连真微信）

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from waimai.models import BuyOrder, PaymentRecord, ShopPaymentSettings, ShopProfile, User
from waimai.pending_payment_timeout_helpers import (
    clamp_timeout_minutes,
    handle_late_wechat_on_cancelled_order,
    pending_pay_stamp_fields,
    process_overdue_order,
    timeout_public_message,
)
from waimai.time_helpers import now_local_wall


class PendingPayTimeoutTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='timeout_seller',
            password='pass12345',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='超时测试店',
            shop_code='toshop',
            address='测试地址',
        )
        ShopPaymentSettings.objects.create(
            seller_id=self.seller.username,
            pending_pay_timeout_minutes=30,
        )

    def _order(self, **kwargs):
        stamp = pending_pay_stamp_fields(self.seller.username)
        stamp['pending_pay_deadline'] = now_local_wall() - timedelta(minutes=1)
        defaults = dict(
            buyer_id='buyer1',
            seller_id=self.seller.username,
            total_amount=Decimal('10.00'),
            dish_items=[{'name': '测试菜', 'qty': 1, 'price': '10.00'}],
            payment_status='pending_payment',
            order_status='created',
            delivery_address='测试地址',
            fulfillment_type='delivery',
        )
        defaults.update(stamp)
        defaults.update(kwargs)
        return BuyOrder.objects.create(**defaults)

    def test_clamp_minutes(self):
        self.assertEqual(clamp_timeout_minutes(0), 5)
        self.assertEqual(clamp_timeout_minutes(30), 30)
        self.assertEqual(clamp_timeout_minutes(99999), 1440)

    def test_overdue_cancels_unpaid(self):
        order = self._order()
        action, msg = process_overdue_order(order)
        order.refresh_from_db()
        self.assertEqual(action, 'cancelled')
        self.assertEqual(order.order_status, 'cancelled')
        self.assertEqual(order.cancel_side, 'system')
        self.assertIn('超过30分钟未支付', msg)
        self.assertEqual(msg, timeout_public_message(order))

    def test_cash_not_cancelled(self):
        order = self._order(payment_method='cash')
        action, _msg = process_overdue_order(order)
        order.refresh_from_db()
        self.assertEqual(action, 'skipped')
        self.assertEqual(order.order_status, 'created')

    def test_idempotent_second_cancel(self):
        order = self._order()
        process_overdue_order(order)
        action, _msg = process_overdue_order(order)
        self.assertEqual(action, 'skipped')

    def test_wechat_success_before_cancel_marks_paid(self):
        order = self._order(payment_method='wechat')

        def fake_peek(o):
            o.payment_status = 'paid'
            o.save(update_fields=['payment_status', 'updated_at'])
            return 'success'

        with patch(
            'waimai.pending_payment_timeout_helpers._wechat_trade_peek',
            side_effect=fake_peek,
        ):
            action, _msg = process_overdue_order(order)
        order.refresh_from_db()
        self.assertEqual(action, 'paid')
        self.assertEqual(order.order_status, 'created')
        self.assertEqual(order.payment_status, 'paid')

    def test_late_pay_does_not_revive(self):
        order = self._order()
        process_overdue_order(order)
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'cancelled')
        PaymentRecord.objects.create(
            buy_order=order,
            payment_method='wechat',
            out_trade_no='TMOUT2',
            amount=order.total_amount,
            status='success',
        )
        order.payment_method = 'wechat'
        order.save(update_fields=['payment_method', 'updated_at'])
        with patch(
            'waimai.payments.wechat_refund_helpers.initiate_wechat_refund_for_order',
            return_value=(False, '微信退款证书未配置或文件不存在，请店主在支付设置中填写 apiclient 证书路径'),
        ) as refund:
            handle_late_wechat_on_cancelled_order(order)
            refund.assert_called_once()
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'cancelled')

    def test_close_channel_before_timeout_cancel(self):
        order = self._order(payment_method='wechat')
        PaymentRecord.objects.create(
            buy_order=order,
            payment_method='wechat',
            out_trade_no='CLOSE1',
            amount=order.total_amount,
            status='pending',
            code_url='weixin://test',
        )
        with patch(
            'waimai.pending_payment_timeout_helpers._wechat_trade_peek',
            return_value='unpaid',
        ), patch(
            'waimai.pending_payment_timeout_helpers.try_close_wechat_channel',
            return_value=('closed', ''),
        ) as closer:
            action, _msg = process_overdue_order(order)
        closer.assert_called()
        order.refresh_from_db()
        self.assertEqual(action, 'cancelled')
        self.assertEqual(order.order_status, 'cancelled')

    def test_wechat_qr_rate_limit(self):
        from waimai.pending_payment_timeout_helpers import wechat_qr_rate_limited

        order = self._order(payment_method='wechat', pending_pay_deadline=now_local_wall() + timedelta(minutes=20))
        for i in range(5):
            PaymentRecord.objects.create(
                buy_order=order,
                payment_method='wechat',
                out_trade_no=f'RATE{i}',
                amount=order.total_amount,
                status='closed',
            )
        self.assertTrue(wechat_qr_rate_limited(order))

    def test_followup_waits_interval(self):
        from waimai.pending_payment_timeout_helpers import followup_query_cancelled_order

        order = self._order(payment_method='wechat')
        process_overdue_order(order)
        order.refresh_from_db()
        PaymentRecord.objects.create(
            buy_order=order,
            payment_method='wechat',
            out_trade_no='FOLL1',
            amount=order.total_amount,
            status='pending',
        )
        order.late_pay_last_query_at = now_local_wall()
        order.save(update_fields=['late_pay_last_query_at', 'updated_at'])
        self.assertEqual(followup_query_cancelled_order(order), 'skipped')
