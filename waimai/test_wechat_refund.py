# V1 · 微信退款最小版（mock 微信接口，不测真网）

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from .time_helpers import now_local_wall

from waimai.fund_ledger_hooks import record_wechat_payment_success
from waimai.models import BuyOrder, FundLedgerEntry, PaymentRecord, ShopPaymentSettings, ShopProfile, User
from waimai.order_cancel_helpers import cancel_order_by_shop, shop_can_cancel_order
from waimai.payments.service import get_payment_settings
from waimai.payments.wechat_refund_helpers import (
    apply_wechat_refund_success,
    initiate_wechat_refund_for_order,
    poll_wechat_refund,
    request_wechat_refund,
    try_sync_wechat_refund,
)
from waimai.staff_account_helpers import PERM_CANCEL_ORDER, staff_internal_username


class WechatRefundTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='refund_seller',
            password='pass12345',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='退款测试店',
            shop_code='refshop',
            address='测试地址',
        )
        self.staff = User.objects.create_user(
            username=staff_internal_username(self.seller.username, '店员A'),
            password='pass12345',
            role='staff',
            employer_seller_id=self.seller.username,
            staff_account_type='employee',
            staff_job_title='店员',
            staff_permissions=[PERM_CANCEL_ORDER],
        )
        self.order = BuyOrder.objects.create(
            buyer_id='buyer1',
            seller_id=self.seller.username,
            total_amount=Decimal('36.00'),
            subtotal_amount=Decimal('36.00'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            payment_method='wechat',
            payment_time=now_local_wall(),
            order_status='awaiting_prep',
            fulfillment_type='takeaway',
        )
        self.record = PaymentRecord.objects.create(
            buy_order=self.order,
            payment_method='wechat',
            out_trade_no='WXREFUNDTEST0001',
            amount=self.order.total_amount,
            status='success',
            provider_trade_no='4200000001',
            paid_at=now_local_wall(),
        )
        record_wechat_payment_success(
            self.order,
            out_trade_no=self.record.out_trade_no,
            source='test',
        )
        pay = get_payment_settings(self.seller.username)
        pay.enable_wechat = True
        pay.wechat_mch_id = '1900000109'
        pay.wechat_app_id = 'wx8888888888888888'
        pay.wechat_api_key = '8934e7d15453e97507ef794cf7b0519d'
        pay.wechat_apiclient_cert_path = __file__
        pay.wechat_apiclient_key_path = __file__
        pay.save()

    def test_staff_cannot_cancel_paid_wechat_order(self):
        self.assertFalse(shop_can_cancel_order(self.staff, self.order))

    def test_owner_can_cancel_paid_wechat_order(self):
        self.assertTrue(shop_can_cancel_order(self.seller, self.order))

    @patch('waimai.payments.wechat_refund_helpers._post_xml_secapi')
    def test_request_refund_success_updates_order_and_ledger(self, mock_post):
        mock_post.return_value = {
            'return_code': 'SUCCESS',
            'result_code': 'SUCCESS',
            'refund_id': '500000001',
            'refund_status': 'SUCCESS',
        }
        settings = get_payment_settings(self.seller.username)
        ok, msg = request_wechat_refund(self.record, settings, operator=self.seller.username)
        self.assertTrue(ok)
        self.assertIn('成功', msg)
        self.record.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.record.refund_status, 'success')
        self.assertEqual(self.order.payment_status, 'refunded')
        self.assertTrue(
            FundLedgerEntry.objects.filter(
                seller_id=self.seller.username,
                direction=FundLedgerEntry.DIRECTION_EXPENSE,
                business_type='wechat_refund_processing',
            ).exists()
        )
        self.assertTrue(
            FundLedgerEntry.objects.filter(
                seller_id=self.seller.username,
                direction=FundLedgerEntry.DIRECTION_EXPENSE,
                business_type='wechat_refund_success',
            ).exists()
        )

    @patch('waimai.payments.wechat_refund_helpers._post_xml_secapi')
    @patch('waimai.payments.wechat_refund_helpers.query_wechat_refund')
    def test_refund_processing_then_poll(self, mock_query, mock_post):
        mock_post.return_value = {
            'return_code': 'SUCCESS',
            'result_code': 'SUCCESS',
            'refund_id': '500000002',
            'refund_status': 'PROCESSING',
        }
        mock_query.return_value = {
            'return_code': 'SUCCESS',
            'result_code': 'SUCCESS',
            'refund_status_0': 'SUCCESS',
            'refund_id_0': '500000002',
        }
        settings = get_payment_settings(self.seller.username)
        ok, _ = request_wechat_refund(self.record, settings, operator=self.seller.username)
        self.assertTrue(ok)
        self.record.refresh_from_db()
        self.assertEqual(self.record.refund_status, 'processing')
        self.assertTrue(
            FundLedgerEntry.objects.filter(
                reference_key=f'wechat_refund:{self.record.out_refund_no}',
                refund_status=FundLedgerEntry.REFUND_STATUS_PROCESSING,
            ).exists()
        )
        self.assertTrue(poll_wechat_refund(self.order))
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'refunded')

    @patch('waimai.payments.wechat_refund_helpers._post_xml_secapi')
    def test_shop_cancel_writes_three_refund_ledger_rows(self, mock_post):
        mock_post.return_value = {
            'return_code': 'SUCCESS',
            'result_code': 'SUCCESS',
            'refund_id': '500000003',
            'refund_status': 'SUCCESS',
        }
        ok, msg = cancel_order_by_shop(
            self.order,
            self.seller,
            note='已与客人电话沟通，同意取消并退款',
        )
        self.assertTrue(ok)
        self.assertIn('取消', msg)
        types = list(
            FundLedgerEntry.objects.filter(
                seller_id=self.seller.username,
                buy_order=self.order,
                direction=FundLedgerEntry.DIRECTION_EXPENSE,
            )
            .order_by('occurred_at', 'ledger_id')
            .values_list('business_type', flat=True)
        )
        self.assertEqual(
            types,
            ['shop_order_cancelled', 'wechat_refund_processing', 'wechat_refund_success'],
        )

    @patch('waimai.payments.wechat_refund_helpers.initiate_wechat_refund_for_order')
    def test_shop_cancel_triggers_refund_for_paid_wechat(self, mock_init):
        mock_init.return_value = (True, '微信退款已成功')
        ok, msg = cancel_order_by_shop(
            self.order,
            self.seller,
            note='已与客人电话沟通，同意取消并退款',
        )
        self.assertTrue(ok)
        mock_init.assert_called_once()
        self.order.refresh_from_db()
        self.assertEqual(self.order.order_status, 'cancelled')

    @patch('waimai.payments.wechat_refund_helpers._post_xml_secapi')
    def test_refund_missing_cert_fails_clearly(self, mock_post):
        pay = get_payment_settings(self.seller.username)
        pay.wechat_apiclient_cert_path = ''
        pay.wechat_apiclient_key_path = ''
        pay.save(update_fields=['wechat_apiclient_cert_path', 'wechat_apiclient_key_path'])
        settings = get_payment_settings(self.seller.username)
        ok, msg = initiate_wechat_refund_for_order(
            self.order, settings, operator=self.seller.username,
        )
        self.assertFalse(ok)
        self.assertIn('证书', msg)
        mock_post.assert_not_called()

    def test_apply_refund_success_is_idempotent(self):
        apply_wechat_refund_success(self.record, operator='test')
        count = FundLedgerEntry.objects.filter(
            seller_id=self.seller.username,
            business_type='wechat_refund_success',
        ).count()
        apply_wechat_refund_success(self.record, operator='test')
        self.assertEqual(
            FundLedgerEntry.objects.filter(
                seller_id=self.seller.username,
                business_type='wechat_refund_success',
            ).count(),
            count,
        )

    @patch('waimai.payments.wechat_refund_helpers.query_wechat_refund')
    def test_try_sync_no_duplicate_expense(self, mock_query):
        self.record.refund_status = 'processing'
        self.record.out_refund_no = 'RTEST0001'
        self.record.save(update_fields=['refund_status', 'out_refund_no', 'updated_at'])
        from waimai.fund_ledger_hooks import record_wechat_refund_processing

        record_wechat_refund_processing(
            self.order,
            out_refund_no=self.record.out_refund_no,
            out_trade_no=self.record.out_trade_no,
            source='test',
        )
        mock_query.return_value = {
            'return_code': 'SUCCESS',
            'result_code': 'SUCCESS',
            'refund_status_0': 'SUCCESS',
        }
        settings = get_payment_settings(self.seller.username)
        self.assertTrue(try_sync_wechat_refund(self.record, settings))
        expense_count = FundLedgerEntry.objects.filter(
            seller_id=self.seller.username,
            direction=FundLedgerEntry.DIRECTION_EXPENSE,
            buy_order=self.order,
        ).count()
        self.assertEqual(expense_count, 2)
