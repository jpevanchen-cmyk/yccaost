# 进度 84 · 现金管理框架（工作台 Tab + 卖家后台分区）

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from waimai.cash_manage_helpers import build_cash_manage_daily_table
from waimai.models import BuyOrder, ShopProfile
from waimai.plugin_runtime.registry import collect_seller_nav_items
from waimai.shop_work_auth import establish_shop_work_session
from waimai.staff_account_helpers import PERM_FULFILLMENT_CASH_MANAGE
from waimai.time_helpers import to_beijing
from waimai.panel_refresh_helpers import PANEL_REQUEST_HEADER
from waimai.workbench_shell_helpers import build_workbench_shell

User = get_user_model()


class CashManageFrameworkTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='cm_seller',
            password='pass12345',
            role='seller',
        )
        self.manager = User.objects.create_user(
            username='cm_mgr',
            password='pass12345',
            role='manager',
            employer_seller_id=self.seller.username,
            staff_permissions=[PERM_FULFILLMENT_CASH_MANAGE],
        )
        self.waiter = User.objects.create_user(
            username='cm_waiter',
            password='pass12345',
            role='waiter',
            employer_seller_id=self.seller.username,
            staff_permissions=['dining.waiter'],
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='现金管理测试店',
            shop_code='cmshop',
            address='测试地址',
        )
        self.client = Client()

    def test_seller_nav_includes_cash_manage_when_fulfillment_on(self):
        sections = {item.section for item in collect_seller_nav_items(self.seller.username)}
        self.assertIn('cash_manage', sections)

    def test_workbench_shell_includes_cash_manage_tab(self):
        shell = build_workbench_shell(self.seller.username)
        self.assertIn('cash_manage', shell.get('enabled_views', []))

    def test_seller_cash_manage_page_renders(self):
        self.client.force_login(self.seller)
        url = reverse('seller_panel_section', kwargs={'section': 'cash_manage'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '外卖现金管理')

    def test_workbench_shows_cash_manage_tab_for_manager(self):
        self.client.force_login(self.manager)
        session = self.client.session
        establish_shop_work_session(
            type('R', (), {'session': session})(),
            self.manager,
            seller_id=self.seller.username,
            shop_code='cmshop',
        )
        session.save()
        url = reverse('shop_work', kwargs={'shop_code': 'cmshop'}) + '?view=cash_manage'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '外卖现金管理')

    def test_workbench_hides_cash_manage_tab_for_waiter_without_perm(self):
        self.client.force_login(self.waiter)
        session = self.client.session
        establish_shop_work_session(
            type('R', (), {'session': session})(),
            self.waiter,
            seller_id=self.seller.username,
            shop_code='cmshop',
        )
        session.save()
        url = reverse('shop_work', kwargs={'shop_code': 'cmshop'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'view=cash_manage')

    def test_order_desk_context_no_longer_includes_remittances(self):
        from waimai.order_desk_helpers import build_order_desk_context

        ctx = build_order_desk_context(
            self.seller.username, work_user=self.seller, sort_mode='newest',
        )
        self.assertNotIn('pending_cash_remittances', ctx)
        self.assertNotIn('cash_exception_orders', ctx)

    def test_daily_table_two_decimals_and_totals(self):
        """按日表格金额两位小数，合计行有数。"""
        now = timezone.now()
        day = to_beijing(now).date().isoformat()
        BuyOrder.objects.create(
            buyer_id='buyer_a',
            seller_id=self.seller.username,
            total_amount=Decimal('91.2'),
            subtotal_amount=Decimal('91.2'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            cash_collected_at=now,
            cash_collected_by='rider1',
            cash_collected_amount=Decimal('91.2000000000000'),
        )
        table = build_cash_manage_daily_table(self.seller.username)
        self.assertEqual(len(table['rows']), 1)
        row = table['rows'][0]
        self.assertEqual(row['date'], day)
        self.assertEqual(row['order_count'], 1)
        self.assertEqual(row['expected_amount'], Decimal('91.20'))
        self.assertEqual(row['unremitted_amount'], Decimal('91.20'))
        self.assertEqual(row['shortfall_amount'], Decimal('0.00'))
        self.assertEqual(table['totals']['order_count'], 1)
        self.assertEqual(table['totals']['unremitted_amount'], Decimal('91.20'))

    def test_daily_table_shortfall_column(self):
        """异常减收列汇总少付差额。"""
        now = timezone.now()
        BuyOrder.objects.create(
            buyer_id='buyer_short',
            seller_id=self.seller.username,
            total_amount=Decimal('100.00'),
            subtotal_amount=Decimal('100.00'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            cash_collected_at=now,
            cash_collected_by='rider1',
            cash_collected_amount=Decimal('90.00'),
            cash_shortfall_status='manager_approved',
        )
        row = build_cash_manage_daily_table(self.seller.username)['rows'][0]
        self.assertEqual(row['expected_amount'], Decimal('100.00'))
        self.assertEqual(row['unremitted_amount'], Decimal('90.00'))
        self.assertEqual(row['shortfall_amount'], Decimal('10.00'))
        self.assertIn('异常减收', row['note'])

    def test_daily_table_auto_note_unremitted(self):
        """未入金时在备注中提示。"""
        now = timezone.now()
        BuyOrder.objects.create(
            buyer_id='buyer_pending',
            seller_id=self.seller.username,
            total_amount=Decimal('50.00'),
            subtotal_amount=Decimal('50.00'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            cash_collected_at=now,
            cash_collected_by='rider1',
            cash_collected_amount=Decimal('50.00'),
        )
        row = build_cash_manage_daily_table(self.seller.username)['rows'][0]
        self.assertIn('尚有未入金', row['note'])

    def test_seller_and_workbench_show_daily_table(self):
        now = timezone.now()
        BuyOrder.objects.create(
            buyer_id='buyer_b',
            seller_id=self.seller.username,
            total_amount=Decimal('10'),
            subtotal_amount=Decimal('10'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            cash_collected_at=now,
            cash_collected_by='rider1',
            cash_collected_amount=Decimal('10.00'),
        )
        self.client.force_login(self.seller)
        seller_url = reverse('seller_panel_section', kwargs={'section': 'cash_manage'})
        response = self.client.get(seller_url)
        self.assertContains(response, '现金单数')
        self.assertContains(response, '外卖现金日汇总')
        self.assertContains(response, 'seller-panel-fold')
        self.assertContains(response, '¥10.00')
        self.assertNotContains(response, '0000000000000')

        self.client.force_login(self.manager)
        session = self.client.session
        establish_shop_work_session(
            type('R', (), {'session': session})(),
            self.manager,
            seller_id=self.seller.username,
            shop_code='cmshop',
        )
        session.save()
        work_url = reverse('shop_work', kwargs={'shop_code': 'cmshop'}) + '?view=cash_manage'
        work_resp = self.client.get(work_url)
        self.assertContains(work_resp, '现金单数')
        self.assertContains(work_resp, '合计')
        self.assertContains(work_resp, '¥10.00')

    def test_cash_month_filter(self):
        from waimai.cash_manage_helpers import resolve_cash_month

        jan = timezone.make_aware(timezone.datetime(2026, 1, 15, 12, 0, 0))
        feb = timezone.make_aware(timezone.datetime(2026, 2, 10, 12, 0, 0))
        BuyOrder.objects.create(
            buyer_id='buyer_jan',
            seller_id=self.seller.username,
            total_amount=Decimal('20'),
            subtotal_amount=Decimal('20'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            cash_collected_at=jan,
            cash_collected_by='rider1',
            cash_collected_amount=Decimal('20'),
        )
        BuyOrder.objects.create(
            buyer_id='buyer_feb',
            seller_id=self.seller.username,
            total_amount=Decimal('30'),
            subtotal_amount=Decimal('30'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            cash_collected_at=feb,
            cash_collected_by='rider1',
            cash_collected_amount=Decimal('30'),
        )
        table = build_cash_manage_daily_table(self.seller.username, year_month='2026-01')
        self.assertEqual(len(table['rows']), 1)
        self.assertEqual(table['rows'][0]['expected_amount'], Decimal('20.00'))
        self.assertEqual(resolve_cash_month('2026-2'), '2026-02')

    def test_workbench_history_fold_and_pagination(self):
        now = timezone.now()
        for idx in range(12):
            BuyOrder.objects.create(
                buyer_id=f'buyer_{idx}',
                seller_id=self.seller.username,
                total_amount=Decimal('1'),
                subtotal_amount=Decimal('1'),
                delivery_fee=Decimal('0'),
                dish_items=[],
                payment_status='pending_payment',
                order_status='created',
                fulfillment_type='delivery',
                created_at=now,
            )
        self.client.force_login(self.seller)
        session = self.client.session
        establish_shop_work_session(
            type('R', (), {'session': session})(),
            self.seller,
            seller_id=self.seller.username,
            shop_code='cmshop',
        )
        session.save()
        url = reverse('shop_work', kwargs={'shop_code': 'cmshop'}) + '?view=orders&hist_per_page=10&hist_page=2'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '今日工作历史')
        self.assertContains(response, 'seller-panel-fold')
        self.assertContains(response, '第 2/')

    def test_seller_cash_month_panel_refresh_returns_json(self):
        """汇总月份下拉走 Panel：返回 JSON 片段，不整页 reload。"""
        jan = timezone.make_aware(timezone.datetime(2026, 1, 15, 12, 0, 0))
        feb = timezone.make_aware(timezone.datetime(2026, 2, 10, 12, 0, 0))
        BuyOrder.objects.create(
            buyer_id='buyer_jan_p',
            seller_id=self.seller.username,
            total_amount=Decimal('20'),
            subtotal_amount=Decimal('20'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            cash_collected_at=jan,
            cash_collected_by='rider1',
            cash_collected_amount=Decimal('20'),
        )
        BuyOrder.objects.create(
            buyer_id='buyer_feb_p',
            seller_id=self.seller.username,
            total_amount=Decimal('30'),
            subtotal_amount=Decimal('30'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            cash_collected_at=feb,
            cash_collected_by='rider1',
            cash_collected_amount=Decimal('30'),
        )
        self.client.force_login(self.seller)
        url = reverse('seller_panel_section', kwargs={'section': 'cash_manage'})
        resp = self.client.get(
            f'{url}?cash_month=2026-01',
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['panel_id'], 'cash-manage-panel-body')
        self.assertIn('¥20.00', data['html'])
        self.assertNotIn('¥30.00', data['html'])
        self.assertIn('data-yc-cash-month-picker', data['html'])

    def test_workbench_cash_month_panel_refresh_returns_json(self):
        """工作台现金 Tab · 月份下拉 Panel 返回 JSON。"""
        jan = timezone.make_aware(timezone.datetime(2026, 1, 20, 12, 0, 0))
        BuyOrder.objects.create(
            buyer_id='buyer_wb_jan',
            seller_id=self.seller.username,
            total_amount=Decimal('15'),
            subtotal_amount=Decimal('15'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            cash_collected_at=jan,
            cash_collected_by='rider1',
            cash_collected_amount=Decimal('15'),
        )
        self.client.force_login(self.manager)
        session = self.client.session
        establish_shop_work_session(
            type('R', (), {'session': session})(),
            self.manager,
            seller_id=self.seller.username,
            shop_code='cmshop',
        )
        session.save()
        url = reverse('shop_work', kwargs={'shop_code': 'cmshop'}) + '?view=cash_manage'
        resp = self.client.get(
            f'{url}&cash_month=2026-01',
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['panel_id'], 'work-cash-manage-panel-body')
        self.assertIn('¥15.00', data['html'])
        self.assertIn('data-yc-cash-month-picker', data['html'])

    def test_workbench_confirm_remittance_panel_json(self):
        """工作台现金 Tab · 确认入金走 Panel JSON。"""
        from waimai.rider_cash_helpers import create_cash_remittance_request

        now = timezone.now()
        BuyOrder.objects.create(
            buyer_id='buyer_remit',
            seller_id=self.seller.username,
            total_amount=Decimal('40'),
            subtotal_amount=Decimal('40'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            cash_collected_at=now,
            cash_collected_by='rider1',
            cash_collected_amount=Decimal('40'),
        )
        remit, create_msg = create_cash_remittance_request(
            self.seller.username, 'rider1',
        )
        self.assertIsNotNone(remit, create_msg)
        self.client.force_login(self.manager)
        session = self.client.session
        establish_shop_work_session(
            type('R', (), {'session': session})(),
            self.manager,
            seller_id=self.seller.username,
            shop_code='cmshop',
        )
        session.save()
        url = reverse('shop_work', kwargs={'shop_code': 'cmshop'}) + '?view=cash_manage'
        resp = self.client.post(
            url,
            {
                'cash_manage_action': 'confirm_remittance',
                'request_id': str(remit.request_id),
            },
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['panel_id'], 'work-cash-manage-panel-body')
        remit.refresh_from_db()
        self.assertEqual(remit.status, 'confirmed')

    def test_seller_confirm_remittance_panel_json(self):
        """卖家后台现金管理 · 确认入金走 Panel JSON。"""
        from waimai.rider_cash_helpers import create_cash_remittance_request

        now = timezone.now()
        BuyOrder.objects.create(
            buyer_id='buyer_seller_remit',
            seller_id=self.seller.username,
            total_amount=Decimal('35'),
            subtotal_amount=Decimal('35'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            cash_collected_at=now,
            cash_collected_by='rider1',
            cash_collected_amount=Decimal('35'),
        )
        remit, create_msg = create_cash_remittance_request(
            self.seller.username, 'rider1',
        )
        self.assertIsNotNone(remit, create_msg)
        self.client.force_login(self.seller)
        url = reverse('seller_panel_section', kwargs={'section': 'cash_manage'})
        resp = self.client.post(
            url,
            {
                'cash_manage_action': 'confirm_remittance',
                'request_id': str(remit.request_id),
            },
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['panel_id'], 'cash-manage-panel-body')
        remit.refresh_from_db()
        self.assertEqual(remit.status, 'confirmed')

    def test_workbench_reject_remittance_panel_json(self):
        """工作台现金 Tab · 退回交款走 Panel JSON。"""
        from waimai.rider_cash_helpers import create_cash_remittance_request

        now = timezone.now()
        BuyOrder.objects.create(
            buyer_id='buyer_reject_remit',
            seller_id=self.seller.username,
            total_amount=Decimal('25'),
            subtotal_amount=Decimal('25'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            cash_collected_at=now,
            cash_collected_by='rider1',
            cash_collected_amount=Decimal('25'),
        )
        remit, create_msg = create_cash_remittance_request(
            self.seller.username, 'rider1',
        )
        self.assertIsNotNone(remit, create_msg)
        self.client.force_login(self.manager)
        session = self.client.session
        establish_shop_work_session(
            type('R', (), {'session': session})(),
            self.manager,
            seller_id=self.seller.username,
            shop_code='cmshop',
        )
        session.save()
        url = reverse('shop_work', kwargs={'shop_code': 'cmshop'}) + '?view=cash_manage'
        resp = self.client.post(
            url,
            {
                'cash_manage_action': 'reject_remittance',
                'request_id': str(remit.request_id),
                'review_note': '现金数额与登记不符',
            },
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        remit.refresh_from_db()
        self.assertEqual(remit.status, 'rejected')
