# 84a · 资金总流水模型与写入点

from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from .time_helpers import now_local_wall

from waimai.fund_ledger_helpers import (
    build_seller_fund_ledger_context,
    compact_ledger_display_no,
    compact_order_display_no,
    fund_status_display,
    record_fund_ledger_if_absent,
    transition_fund_ledger_entry,
)
from waimai.fund_ledger_hooks import record_order_payment_received, record_wechat_scan_initiated
from waimai.models import BuyOrder, FundLedgerEntry, FundLedgerStatusTrack, ShopProfile, User


class FundLedgerModelTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='fl_seller',
            password='pass12345',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='流水测试店',
            shop_code='flshop',
            address='测试地址',
        )
        self.order = BuyOrder.objects.create(
            buyer_id='buyer1',
            seller_id=self.seller.username,
            total_amount=Decimal('28.00'),
            subtotal_amount=Decimal('28.00'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            payment_method='wechat_simulate',
            payment_time=now_local_wall(),
            order_status='awaiting_prep',
            fulfillment_type='takeaway',
        )

    def test_create_entry_with_status_track(self):
        entry = record_fund_ledger_if_absent(
            self.order,
            reference_key='paid:test:wechat_simulate',
            direction=FundLedgerEntry.DIRECTION_INCOME,
            amount=self.order.total_amount,
            payment_method='wechat_simulate',
            business_type='demo_payment_success',
            source='test',
            operator='system',
            fund_status=FundLedgerEntry.FUND_STATUS_AT_SHOP,
        )
        self.assertIsNotNone(entry)
        self.assertTrue(entry.display_no.startswith('FL-'))
        self.assertGreaterEqual(entry.status_tracks.count(), 1)

    def test_idempotent_reference_key_skips_duplicate(self):
        record_fund_ledger_if_absent(
            self.order,
            reference_key='paid:dup',
            direction=FundLedgerEntry.DIRECTION_INCOME,
            amount=self.order.total_amount,
            payment_method='cash',
            business_type='payment_received',
            source='test',
        )
        again = record_fund_ledger_if_absent(
            self.order,
            reference_key='paid:dup',
            direction=FundLedgerEntry.DIRECTION_INCOME,
            amount=self.order.total_amount,
            payment_method='cash',
            business_type='payment_received',
            source='test',
        )
        self.assertIsNone(again)
        self.assertEqual(FundLedgerEntry.objects.filter(reference_key='paid:dup').count(), 1)

    def test_transition_appends_track_only(self):
        entry = record_fund_ledger_if_absent(
            self.order,
            reference_key='collect:1',
            direction=FundLedgerEntry.DIRECTION_INCOME,
            amount=Decimal('20.00'),
            payment_method='cash',
            business_type='rider_cash_collected',
            source='test',
            fund_status=FundLedgerEntry.FUND_STATUS_IN_TRANSIT,
        )
        before = FundLedgerStatusTrack.objects.count()
        transition_fund_ledger_entry(
            entry,
            fund_status=FundLedgerEntry.FUND_STATUS_AT_SHOP,
            operator='boss',
            source='test_remit',
        )
        entry.refresh_from_db()
        self.assertEqual(entry.fund_status, FundLedgerEntry.FUND_STATUS_AT_SHOP)
        self.assertGreater(FundLedgerStatusTrack.objects.count(), before)

    def test_payment_hook_writes_ledger(self):
        record_order_payment_received(
            self.order,
            'wechat_simulate',
            source='test_hook',
            operator='system',
        )
        self.assertTrue(
            FundLedgerEntry.objects.filter(
                buy_order=self.order,
                business_type='demo_payment_success',
            ).exists()
        )

    def test_compact_display_numbers(self):
        self.assertEqual(compact_ledger_display_no('FL-20260806-34E5F05F'), 'FL-34E5F05F')
        self.assertEqual(compact_order_display_no(self.order), self.order.get_order_short_code())

    def test_wechat_scan_pending_arrival_label(self):
        record_wechat_scan_initiated(
            self.order,
            out_trade_no='WXSCAN001',
            source='test',
        )
        entry = FundLedgerEntry.objects.get(reference_key='wechat_init:WXSCAN001')
        self.assertEqual(entry.fund_status, FundLedgerEntry.FUND_STATUS_PENDING_ARRIVAL)
        self.assertEqual(
            fund_status_display(entry.fund_status, business_type=entry.business_type),
            '待到账',
        )
        self.assertEqual(
            fund_status_display(
                FundLedgerEntry.FUND_STATUS_NOT_APPLICABLE,
                business_type='wechat_scan_initiated',
            ),
            '待到账',
        )


class FundLedgerPageTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='fl_page_seller',
            password='pass12345',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='流水页测试店',
            shop_code='flpage',
            address='测试地址',
        )
        self.order = BuyOrder.objects.create(
            buyer_id='buyer2',
            seller_id=self.seller.username,
            total_amount=Decimal('15.00'),
            subtotal_amount=Decimal('15.00'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            payment_method='cash',
            payment_time=now_local_wall(),
            order_status='completed',
            fulfillment_type='delivery',
        )
        record_order_payment_received(
            self.order,
            'cash',
            source='test_page',
            operator='system',
            fund_status=FundLedgerEntry.FUND_STATUS_IN_TRANSIT,
        )
        self.client = Client()
        self.client.force_login(self.seller)

    def test_seller_fund_ledger_page_renders(self):
        url = reverse('seller_panel_section', kwargs={'section': 'fund_ledger'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '资金流水')
        self.assertContains(response, 'seller-table')
        self.assertContains(response, 'fund-ledger-drawer')
        self.assertContains(response, 'yc-fl-drawer-link')
        self.assertContains(response, self.order.get_order_short_code())
        entry = FundLedgerEntry.objects.filter(buy_order=self.order).first()
        self.assertIsNotNone(entry)
        self.assertContains(response, compact_ledger_display_no(entry.display_no))

    def test_entry_drawer_returns_html(self):
        entry = FundLedgerEntry.objects.filter(buy_order=self.order).first()
        url = reverse('seller_fund_ledger_entry_drawer', kwargs={'ledger_id': entry.ledger_id})
        response = self.client.get(url, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertIn(entry.display_no, data['html'])
        self.assertIn('状态追踪', data['html'])

    def test_order_drawer_returns_html(self):
        url = reverse('seller_fund_ledger_order_drawer', kwargs={'order_id': self.order.order_id})
        response = self.client.get(url, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertIn(self.order.get_order_short_code(), data['html'])
        self.assertIn('本单资金明细', data['html'])

    def test_drawer_rejects_other_seller(self):
        other = User.objects.create_user(username='other_fl', password='pass12345', role='seller')
        entry = FundLedgerEntry.objects.filter(buy_order=self.order).first()
        self.client.force_login(other)
        url = reverse('seller_fund_ledger_entry_drawer', kwargs={'ledger_id': entry.ledger_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_cash_tab_filters_same_table(self):
        ctx = build_seller_fund_ledger_context(self.seller.username, type('R', (), {'GET': {'tab': 'cash'}})())
        self.assertEqual(ctx['fund_ledger_tab'], 'cash')
        self.assertEqual(len(ctx['fund_ledger_entries']), 1)

    def test_nav_includes_fund_ledger(self):
        from waimai.plugin_runtime.registry import collect_seller_nav_items

        sections = {item.section for item in collect_seller_nav_items(self.seller.username)}
        self.assertIn('fund_ledger', sections)


class FundLedger84bTests(TestCase):
    """84b：搜索、按日汇总、双收告警、入金/少收视图。"""

    def setUp(self):
        self.seller = User.objects.create_user(
            username='fl84b_seller',
            password='pass12345',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='84b测试店',
            shop_code='fl84b',
            address='测试地址',
        )
        self.order = BuyOrder.objects.create(
            buyer_id='buyer84b',
            seller_id=self.seller.username,
            total_amount=Decimal('30.00'),
            subtotal_amount=Decimal('30.00'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            payment_method='wechat',
            payment_time=now_local_wall(),
            order_status='completed',
            fulfillment_type='takeaway',
        )
        self.client = Client()
        self.client.force_login(self.seller)

    def _req(self, params):
        return type('R', (), {'GET': params})()

    def test_search_by_note(self):
        from waimai.fund_ledger_helpers import create_fund_ledger_entry

        create_fund_ledger_entry(
            self.order,
            direction=FundLedgerEntry.DIRECTION_INCOME,
            amount=Decimal('30.00'),
            payment_method='wechat',
            business_type='wechat_payment_success',
            source='test',
            note='特殊备注关键字甲',
            fund_status=FundLedgerEntry.FUND_STATUS_AT_SHOP,
        )
        ctx = build_seller_fund_ledger_context(
            self.seller.username, self._req({'q': '关键字甲'}),
        )
        self.assertEqual(len(ctx['fund_ledger_entries']), 1)
        self.assertIn('关键字甲', ctx['fund_ledger_entries'][0]['note'])

    def test_daily_summary_counts_success(self):
        from waimai.fund_ledger_helpers import create_fund_ledger_entry, build_fund_ledger_daily_summary
        from waimai.time_helpers import to_local

        create_fund_ledger_entry(
            self.order,
            direction=FundLedgerEntry.DIRECTION_INCOME,
            amount=Decimal('30.00'),
            payment_method='wechat',
            business_type='wechat_payment_success',
            source='test',
            fund_status=FundLedgerEntry.FUND_STATUS_AT_SHOP,
        )
        month = to_local(now_local_wall()).date().strftime('%Y-%m')
        daily = build_fund_ledger_daily_summary(self.seller.username, year_month=month)
        self.assertGreaterEqual(daily['totals']['entry_count'], 1)
        self.assertEqual(daily['totals']['income_amount'], Decimal('30.00'))

    def test_double_income_alert(self):
        from waimai.fund_ledger_helpers import (
            create_fund_ledger_entry,
            detect_fund_ledger_order_alerts,
        )

        create_fund_ledger_entry(
            self.order,
            direction=FundLedgerEntry.DIRECTION_INCOME,
            amount=Decimal('30.00'),
            payment_method='wechat',
            business_type='wechat_payment_success',
            source='test1',
            fund_status=FundLedgerEntry.FUND_STATUS_AT_SHOP,
        )
        create_fund_ledger_entry(
            self.order,
            direction=FundLedgerEntry.DIRECTION_INCOME,
            amount=Decimal('30.00'),
            payment_method='cash',
            business_type='payment_received',
            source='test2',
            fund_status=FundLedgerEntry.FUND_STATUS_AT_SHOP,
        )
        alerts = detect_fund_ledger_order_alerts(self.seller.username)
        self.assertIn(str(self.order.order_id), alerts)
        self.assertIn('疑似双收', alerts[str(self.order.order_id)])
        ctx = build_seller_fund_ledger_context(
            self.seller.username, self._req({'view': 'alerts'}),
        )
        self.assertEqual(ctx['fund_ledger_alert_order_count'], 1)
        self.assertTrue(any(row['is_alert'] for row in ctx['fund_ledger_entries']))

    def test_remit_and_shortfall_views(self):
        from waimai.fund_ledger_helpers import create_fund_ledger_entry

        create_fund_ledger_entry(
            self.order,
            direction=FundLedgerEntry.DIRECTION_INCOME,
            amount=Decimal('28.00'),
            payment_method='cash',
            business_type='cash_remittance_confirmed',
            source='test',
            fund_status=FundLedgerEntry.FUND_STATUS_AT_SHOP,
        )
        create_fund_ledger_entry(
            self.order,
            direction=FundLedgerEntry.DIRECTION_INCOME,
            amount=Decimal('25.00'),
            payment_method='cash',
            business_type='cash_exception_settled',
            source='test',
            note='少收兜底',
            fund_status=FundLedgerEntry.FUND_STATUS_IN_TRANSIT,
        )
        remit = build_seller_fund_ledger_context(
            self.seller.username, self._req({'view': 'remit', 'tab': 'cash'}),
        )
        self.assertEqual(len(remit['fund_ledger_entries']), 1)
        self.assertEqual(remit['fund_ledger_entries'][0]['business_type'], '入金确认')
        shortfall = build_seller_fund_ledger_context(
            self.seller.username, self._req({'view': 'shortfall'}),
        )
        self.assertEqual(len(shortfall['fund_ledger_entries']), 1)
        self.assertEqual(shortfall['fund_ledger_entries'][0]['business_type'], '少收兜底结单')

    def test_page_shows_84b_controls(self):
        url = reverse('seller_panel_section', kwargs={'section': 'fund_ledger'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '按日汇总')
        self.assertContains(response, '入金历史')
        self.assertContains(response, '少收明细')
        self.assertContains(response, '异常告警')
        self.assertContains(response, 'fund-ledger-subtabs')
        self.assertContains(response, 'name="q"')
        daily = self.client.get(url, {'view': 'daily'})
        self.assertEqual(daily.status_code, 200)
        self.assertContains(daily, '汇总月份')
        self.assertContains(daily, 'fund-ledger-subtabs')
