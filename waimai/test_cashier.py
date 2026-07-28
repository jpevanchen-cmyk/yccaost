# 实体收银台第一期验收

from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from waimai.cashier_helpers import (
    cashier_can_start_wechat,
    cashier_confirm_payment,
    cashier_wechat_options,
    merge_channel_options,
    query_cashier_pending_orders,
)
from waimai.models import BuyOrder, ShopProfile, User
from waimai.payments.core import get_payment_settings
from waimai.staff_account_helpers import (
    PERM_FULFILLMENT_CASH_MANAGE,
    PERM_ORDERS_CASHIER,
    staff_internal_username,
)
from waimai.workbench_shell_helpers import build_workbench_shell

# 单元测试占位：非真实微信商户参数（勿用 32 位类密钥格式，避免 GitHub 误报）
_FAKE_WECHAT_MCH_ID = 'unit-test-mch-not-real'
_FAKE_WECHAT_APP_ID = 'unit-test-app-not-real'
_FAKE_WECHAT_API_KEY = 'NOT_A_REAL_WECHAT_KEY'


def _apply_fake_wechat_settings(pay):
    """测试里模拟「微信参数已配齐」"""
    pay.enable_wechat = True
    pay.wechat_mch_id = _FAKE_WECHAT_MCH_ID
    pay.wechat_app_id = _FAKE_WECHAT_APP_ID
    pay.wechat_api_key = _FAKE_WECHAT_API_KEY
    pay.save()


class CashierBase(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='cash_seller', password='seller-pass-123', role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='收银试验店',
            shop_code='cashshop',
            address='试验地址',
        )
        pay = get_payment_settings(self.seller.username)
        pay.enable_cashier = True
        pay.enable_cash = True
        pay.cashier_page_size = 10
        pay.save()

        self.clerk = User.objects.create_user(
            username=staff_internal_username(self.seller.username, '收银'),
            password='clerk-pass-123',
            role='staff',
            employer_seller_id=self.seller.username,
            staff_account_type='employee',
            staff_job_title='收银员',
            staff_permissions=[PERM_ORDERS_CASHIER],
        )
        self.manager = User.objects.create_user(
            username=staff_internal_username(self.seller.username, '店长'),
            password='mgr-pass-123',
            role='staff',
            employer_seller_id=self.seller.username,
            staff_account_type='management',
            staff_job_title='店长',
            staff_permissions=[PERM_ORDERS_CASHIER, PERM_FULFILLMENT_CASH_MANAGE],
        )

    def make_pending_order(self, **overrides):
        values = {
            'buyer_id': 'buyer1',
            'seller_id': self.seller.username,
            'total_amount': Decimal('30.00'),
            'subtotal_amount': Decimal('30.00'),
            'dish_items': [{'dish_id': 'd1', 'name': '试验商品', 'price': 30, 'quantity': 1}],
            'payment_status': 'pending_payment',
            'order_status': 'awaiting_payment',
            'fulfillment_type': 'order',
        }
        values.update(overrides)
        return BuyOrder.objects.create(**values)


class CashierHelperTests(CashierBase):
    def test_shell_shows_cashier_tab_when_enabled(self):
        views = build_workbench_shell(self.seller.username).get('enabled_views') or []
        self.assertIn('cashier', views)

    def test_query_today_pending_only(self):
        today_order = self.make_pending_order()
        old_order = self.make_pending_order()
        BuyOrder.objects.filter(pk=old_order.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=2),
        )
        paid_order = self.make_pending_order(payment_status='paid', order_status='awaiting_prep')

        ids = set(query_cashier_pending_orders(self.seller.username).values_list('order_id', flat=True))
        self.assertIn(today_order.order_id, ids)
        self.assertNotIn(old_order.order_id, ids)
        self.assertNotIn(paid_order.order_id, ids)

    def test_cash_collect_success(self):
        order = self.make_pending_order()
        ok, msg = cashier_confirm_payment(
            order,
            actor=self.clerk,
            pay_mode='cash',
            collected_amount='30.00',
            can_manage_shortfall=False,
        )
        self.assertTrue(ok)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.payment_method, 'cash')
        self.assertEqual(order.cash_collected_amount, Decimal('30.00'))
        self.assertEqual(order.order_status, 'awaiting_prep')

    def test_takeaway_advances_order_flow(self):
        order = self.make_pending_order(
            fulfillment_type='takeaway',
            payment_method='cash',
        )
        ok, msg = cashier_confirm_payment(
            order,
            actor=self.clerk,
            pay_mode='cash',
            collected_amount='30.00',
            can_manage_shortfall=False,
        )
        self.assertTrue(ok)
        self.assertIn('备货', msg)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.order_status, 'awaiting_prep')

    def test_in_store_already_prepping_only_marks_paid(self):
        order = self.make_pending_order(
            fulfillment_type='takeaway',
            payment_method='cash',
            order_status='preparing',
        )
        ok, _ = cashier_confirm_payment(
            order,
            actor=self.clerk,
            pay_mode='cash',
            collected_amount='30.00',
            can_manage_shortfall=False,
        )
        self.assertTrue(ok)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.order_status, 'preparing')

    def test_shortfall_manager_approved_and_advances_flow(self):
        order = self.make_pending_order(fulfillment_type='takeaway', payment_method='cash')
        ok, _ = cashier_confirm_payment(
            order,
            actor=self.manager,
            pay_mode='cash',
            collected_amount='25.00',
            shortfall_reason='抹零优惠',
            can_manage_shortfall=True,
        )
        self.assertTrue(ok)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.order_status, 'awaiting_prep')
        self.assertEqual(order.cash_shortfall_status, 'manager_approved')

    def test_external_collect_remembers_channel(self):
        order = self.make_pending_order()
        settings = get_payment_settings(self.seller.username)
        ok, _ = cashier_confirm_payment(
            order,
            actor=self.clerk,
            pay_mode='external',
            collected_amount='30.00',
            channel='店外 POS',
            can_manage_shortfall=False,
        )
        self.assertTrue(ok)
        settings.refresh_from_db()
        self.assertIn('店外 POS', merge_channel_options(settings))

    def test_shortfall_blocked_without_manage(self):
        order = self.make_pending_order()
        ok, msg = cashier_confirm_payment(
            order,
            actor=self.clerk,
            pay_mode='cash',
            collected_amount='25.00',
            shortfall_reason='抹零',
            can_manage_shortfall=False,
        )
        self.assertFalse(ok)
        self.assertIn('管理', msg)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'pending_payment')

    def test_shortfall_allowed_with_manage(self):
        order = self.make_pending_order()
        ok, msg = cashier_confirm_payment(
            order,
            actor=self.manager,
            pay_mode='cash',
            collected_amount='25.00',
            shortfall_reason='抹零优惠',
            can_manage_shortfall=True,
        )
        self.assertTrue(ok)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.cash_collected_amount, Decimal('25.00'))
        self.assertEqual(order.order_status, 'awaiting_prep')
        self.assertEqual(order.cash_shortfall_status, 'manager_approved')


class CashierWorkbenchTests(CashierBase):
    def _login_work(self, client, display_name: str, password: str):
        return client.post(
            '/s/cashshop/work/',
            {'username': display_name, 'password': password},
        )

    def test_workbench_cashier_tab_and_post(self):
        order = self.make_pending_order()
        client = Client()
        self._login_work(client, '收银', 'clerk-pass-123')
        resp = client.get('/s/cashshop/work/?view=cashier')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '实体收银台')
        self.assertContains(resp, order.get_display_order_no())

        resp = client.post(
            '/s/cashshop/work/?view=cashier',
            {
                'cashier_action': 'collect',
                'order_id': str(order.order_id),
                'pay_mode': 'cash',
                'collected_amount': '30.00',
            },
        )
        self.assertEqual(resp.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.order_status, 'awaiting_prep')

    def test_clerk_without_cashier_perm_no_tab(self):
        User.objects.create_user(
            username=staff_internal_username(self.seller.username, '后厨'),
            password='k-pass-123',
            role='staff',
            employer_seller_id=self.seller.username,
            staff_permissions=['dining.kitchen', 'orders.view'],
        )
        client = Client()
        self._login_work(client, '后厨', 'k-pass-123')
        resp = client.get('/s/cashshop/work/?view=cashier')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, '实体收银台')


class CashierQrPhase3Tests(CashierBase):
    def _login_work(self, client):
        client.post(
            '/s/cashshop/work/',
            {'username': '收银', 'password': 'clerk-pass-123'},
        )

    def test_order_qr_bundle_contains_lookup_url(self):
        from django.test import RequestFactory

        from waimai.order_qr_helpers import build_order_cashier_qr_bundle, build_order_barcode_payload

        order = self.make_pending_order()
        request = RequestFactory().get('/')
        bundle = build_order_cashier_qr_bundle(request, order, 'cashshop')
        self.assertIsNotNone(bundle)
        self.assertIn('/s/cashshop/work/', bundle['lookup_url'])
        self.assertIn('view=cashier', bundle['lookup_url'])
        self.assertIn(order.get_display_order_no(), bundle['lookup_url'])
        self.assertEqual(bundle['barcode_payload'], build_order_barcode_payload(order))
        self.assertTrue(bundle['qr_data_url'].startswith('data:image/png;base64,'))
        if bundle['barcode_data_url']:
            self.assertTrue(bundle['barcode_data_url'].startswith('data:image/png;base64,'))

    def test_order_detail_ok_when_barcode_lib_missing(self):
        """未装 python-barcode 时，订单详情仍应能打开（仅无条形码）。"""
        import sys
        from unittest.mock import patch

        from django.test import Client

        order = self.make_pending_order()
        buyer = User.objects.create_user(
            username='cash_buyer1', password='buyer-pass-123', role='buyer',
        )
        order.buyer_id = buyer.username
        order.save(update_fields=['buyer_id'])

        client = Client()
        client.force_login(buyer)
        with patch.dict(sys.modules, {'barcode': None, 'barcode.codex': None, 'barcode.writer': None}):
            resp = client.get(f'/order/{order.order_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, order.get_display_order_no())

    def test_print_page_requires_cashier_perm(self):
        order = self.make_pending_order()
        client = Client()
        resp = client.get(f'/s/cashshop/work/cashier/print/{order.order_id}/')
        self.assertEqual(resp.status_code, 302)

    def test_print_page_ok_for_cashier(self):
        order = self.make_pending_order()
        client = Client()
        self._login_work(client)
        resp = client.get(f'/s/cashshop/work/cashier/print/{order.order_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, order.get_display_order_no())
        self.assertContains(resp, '订单条形码')

    def test_cashier_search_by_q_param(self):
        order = self.make_pending_order()
        client = Client()
        self._login_work(client)
        short = order.get_order_short_code()
        resp = client.get(f'/s/cashshop/work/?view=cashier&q={short}')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, order.get_display_order_no())

    def test_simulate_pay_advances_order(self):
        from waimai.cashier_helpers import cashier_confirm_simulate_payment

        pay = get_payment_settings(self.seller.username)
        pay.enable_simulate = True
        pay.save()
        order = self.make_pending_order(fulfillment_type='takeaway')
        ok, _ = cashier_confirm_simulate_payment(order, actor=self.clerk)
        self.assertTrue(ok)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.payment_method, 'wechat_simulate')
        self.assertEqual(order.order_status, 'awaiting_prep')

    def test_simulate_pay_post_from_cashier_tab(self):
        pay = get_payment_settings(self.seller.username)
        pay.enable_simulate = True
        pay.save()
        order = self.make_pending_order(fulfillment_type='takeaway')
        client = Client()
        self._login_work(client)
        resp = client.post(
            '/s/cashshop/work/?view=cashier',
            {
                'cashier_action': 'simulate_pay',
                'order_id': str(order.order_id),
            },
        )
        self.assertEqual(resp.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.order_status, 'awaiting_prep')

    def test_seller_print_page(self):
        order = self.make_pending_order()
        client = Client()
        client.force_login(self.seller)
        resp = client.get(f'/seller-panel/orders/cashier-qr/{order.order_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, order.get_display_order_no())


class CashierWechatTests(CashierBase):
    def test_wechat_hidden_when_not_configured(self):
        opts = cashier_wechat_options(self.seller.username)
        self.assertFalse(opts['cashier_enable_wechat'])

    def test_wechat_shown_when_ready(self):
        pay = get_payment_settings(self.seller.username)
        _apply_fake_wechat_settings(pay)
        opts = cashier_wechat_options(self.seller.username)
        self.assertTrue(opts['cashier_enable_wechat'])

    def test_start_wechat_redirects_to_qr_page(self):
        pay = get_payment_settings(self.seller.username)
        _apply_fake_wechat_settings(pay)
        order = self.make_pending_order(fulfillment_type='takeaway')
        client = Client()
        client.post(
            '/s/cashshop/work/',
            {'username': '收银', 'password': 'clerk-pass-123'},
        )
        resp = client.post(
            '/s/cashshop/work/?view=cashier',
            {
                'cashier_action': 'start_wechat',
                'order_id': str(order.order_id),
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/work/cashier/wechat/', resp.url)

    def test_cannot_start_wechat_for_paid_order(self):
        pay = get_payment_settings(self.seller.username)
        _apply_fake_wechat_settings(pay)
        order = self.make_pending_order(
            payment_status='paid',
            order_status='awaiting_prep',
        )
        ok, msg = cashier_can_start_wechat(order, self.seller.username)
        self.assertFalse(ok)
