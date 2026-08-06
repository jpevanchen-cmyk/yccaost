# 84a · 资金总流水模型与写入点

from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from waimai.fund_ledger_helpers import (
    build_seller_fund_ledger_context,
    compact_ledger_display_no,
    compact_order_display_no,
    record_fund_ledger_if_absent,
    transition_fund_ledger_entry,
)
from waimai.fund_ledger_hooks import record_order_payment_received
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
            payment_time=timezone.now(),
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
            payment_time=timezone.now(),
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
