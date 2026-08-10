# B 阶段：服务员代客开台后自动进点菜页、帮此桌点餐、代下审计

from datetime import time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from waimai.channel_helpers import CHANNEL_DINE_IN, get_shop_channel
from waimai.dine_models import ShopTable
from waimai.models import BuyOrder, MenuProfileItem, OperationAuditLog
from waimai.operating_helpers import get_operating_settings
from waimai.plugins.dining.table_helpers import (
    open_table_main_session,
    table_main_session_is_active,
)
from waimai.plugins.dining.waiter_table_order_helpers import (
    is_waiter_table_order_active,
)
from waimai.shop_work_auth import establish_shop_work_session
from waimai.staff_account_helpers import PERM_DINING_WAITER, staff_internal_username
from waimai.test_shop_helpers import create_test_shop_bundle

User = get_user_model()


class WaiterTableOrderFlowTests(TestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='wt_order_seller',
            password='seller-pass-123',
            shop_code='wtord',
            shop_name='代客点菜试验店',
            with_menu=True,
            with_dish=True,
            dish_price=Decimal('15.00'),
        )
        self.seller_id = bundle.seller.username
        self.shop_code = bundle.shop.shop_code
        self.dish = bundle.dish
        settings = get_operating_settings(self.seller_id)
        settings.plugin_dining_enabled = True
        settings.dine_channel_enabled = True
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=[
            'plugin_dining_enabled', 'dine_channel_enabled',
            'business_open', 'business_close',
        ])
        MenuProfileItem.objects.filter(
            profile=bundle.profile, dish=self.dish,
        ).update(sales_cap=20, sold_count=0)
        self.table = ShopTable.objects.create(
            seller_id=self.seller_id,
            table_number='3',
            is_active=True,
        )
        self.waiter = User.objects.create_user(
            username=staff_internal_username(self.seller_id, '代客点菜'),
            password='waiter-pass-123',
            role='staff',
            employer_seller_id=self.seller_id,
            staff_account_type='employee',
            staff_job_title='服务员',
            staff_permissions=[PERM_DINING_WAITER],
        )
        self.client = Client()
        session = self.client.session
        establish_shop_work_session(
            type('R', (), {'session': session})(),
            self.waiter,
            seller_id=self.seller_id,
            shop_code=self.shop_code,
        )
        session.save()

    def _work_url(self):
        return reverse('shop_work', kwargs={'shop_code': self.shop_code})

    def _order_page_url(self):
        return reverse(
            'shop_work_waiter_table_order',
            kwargs={'shop_code': self.shop_code, 'table_id': self.table.table_id},
        )

    def test_open_table_redirects_to_order_page(self):
        resp = self.client.post(
            f'{self._work_url()}?view=waiter',
            {'waiter_open_table': '1', 'table_id': str(self.table.table_id)},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], self._order_page_url())

    def test_waiter_order_page_shows_banner_and_dine_channel(self):
        open_table_main_session(self.table)
        resp = self.client.get(self._order_page_url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '服务员代客点菜')
        self.assertContains(resp, '3号桌')
        self.assertTrue(is_waiter_table_order_active(self.client, self.seller_id))
        self.assertEqual(get_shop_channel(self.client.session, self.seller_id), CHANNEL_DINE_IN)

    def test_waiter_place_order_writes_audit(self):
        open_table_main_session(self.table)
        order_url = self._order_page_url()
        self.client.get(order_url)
        self.client.post(order_url, {
            'action': 'add_to_cart',
            'dish_id': self.dish.dish_id,
            'price_tier': 'general',
        })
        self.client.post(order_url, {'action': 'checkout'})
        resp = self.client.post('/place-order/', {
            'seller_id': self.seller_id,
            'fulfillment_type': CHANNEL_DINE_IN,
            'dine_in_at_shop': '1',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(BuyOrder.objects.filter(seller_id=self.seller_id).count(), 1)
        log = OperationAuditLog.objects.filter(
            seller_id=self.seller_id,
            action_code='order_place',
        ).order_by('-created_at').first()
        self.assertIsNotNone(log)
        self.assertIn('服务员代下', log.summary)

    def test_help_order_for_busy_table(self):
        open_table_main_session(self.table)
        resp = self.client.get(f'{self._work_url()}?view=waiter')
        self.assertContains(resp, '帮此桌点餐')
        self.assertContains(resp, self._order_page_url())


class WaiterTableBoardPollTests(TestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='wt_poll_seller',
            password='seller-pass-123',
            shop_code='wtpoll',
            shop_name='桌台轮询试验店',
        )
        self.seller_id = bundle.seller.username
        self.shop_code = bundle.shop.shop_code
        settings = get_operating_settings(self.seller_id)
        settings.plugin_dining_enabled = True
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=['plugin_dining_enabled', 'business_open', 'business_close'])
        ShopTable.objects.create(
            seller_id=self.seller_id,
            table_number='5',
            is_active=True,
        )
        self.waiter = User.objects.create_user(
            username=staff_internal_username(self.seller_id, '桌台轮询'),
            password='waiter-pass-123',
            role='staff',
            employer_seller_id=self.seller_id,
            staff_account_type='employee',
            staff_job_title='服务员',
            staff_permissions=[PERM_DINING_WAITER],
        )
        self.client = Client()
        session = self.client.session
        establish_shop_work_session(
            type('R', (), {'session': session})(),
            self.waiter,
            seller_id=self.seller_id,
            shop_code=self.shop_code,
        )
        session.save()

    def test_table_board_poll_returns_inner_html(self):
        url = reverse('shop_work', kwargs={'shop_code': self.shop_code})
        resp = self.client.get(
            f'{url}?view=waiter&yc_table_board=1',
            HTTP_X_REQUESTED_WITH='YecaoPanel',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('ok'))
        self.assertIn('waiter-table-tile', data.get('html', ''))
        self.assertIn('5', data.get('html', ''))
