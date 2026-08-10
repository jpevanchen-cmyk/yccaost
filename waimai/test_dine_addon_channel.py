# A 阶段：桌台通道绑定、过期会话、服务员翻台、加点二维码

from datetime import time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from waimai.channel_helpers import CHANNEL_DINE_IN, get_shop_channel
from waimai.dine_models import ShopTable
from waimai.models import MenuProfileItem
from waimai.operating_helpers import get_operating_settings
from waimai.plugins.dining.buyer_entry import (
    addon_token_session_key,
    build_table_continue_dine_url,
)
from waimai.plugins.dining.table_helpers import (
    close_table_session,
    ensure_addon_token,
    open_table_main_session,
    table_main_session_is_active,
)
from waimai.plugins.dining.waiter_table_helpers import (
    build_waiter_table_board_context,
    waiter_close_table,
)
from waimai.shop_work_auth import establish_shop_work_session
from waimai.staff_account_helpers import PERM_DINING_WAITER, staff_internal_username
from waimai.test_shop_helpers import create_test_shop_bundle

User = get_user_model()


class DineAddonChannelTests(TestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='dine_ch_seller',
            password='seller-pass-123',
            shop_code='dinech',
            shop_name='通道绑定试验店',
            with_menu=True,
            with_dish=True,
            dish_price=Decimal('12.00'),
        )
        self.seller_id = bundle.seller.username
        self.dish = bundle.dish
        settings = get_operating_settings(self.seller_id)
        settings.plugin_dining_enabled = True
        settings.dine_channel_enabled = True
        settings.takeaway_channel_enabled = True
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=[
            'plugin_dining_enabled', 'dine_channel_enabled', 'takeaway_channel_enabled',
            'business_open', 'business_close',
        ])
        MenuProfileItem.objects.filter(
            profile=bundle.profile, dish=self.dish,
        ).update(sales_cap=20, sold_count=0)
        self.table = ShopTable.objects.create(
            seller_id=self.seller_id,
            table_number='6',
            is_active=True,
        )
        self.client = Client()

    def test_addon_entry_locks_dine_channel(self):
        session, _ = open_table_main_session(self.table)
        token = ensure_addon_token(session)
        url = f'/dine/?seller_id={self.seller_id}&s={token}'
        self.client.get(url)
        self.assertEqual(get_shop_channel(self.client.session, self.seller_id), CHANNEL_DINE_IN)
        self.assertEqual(
            self.client.session.get(addon_token_session_key(self.seller_id)),
            token,
        )

    def test_addon_shop_page_no_channel_pick(self):
        session, _ = open_table_main_session(self.table)
        token = ensure_addon_token(session)
        self.client.get(f'/dine/?seller_id={self.seller_id}&s={token}')
        resp = self.client.get(f'/shop/?seller_id={self.seller_id}')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, '请先选择下单方式')
        self.assertContains(resp, '当前桌台')

    def test_guest_place_order_then_still_dine_not_channel_pick(self):
        session, _ = open_table_main_session(self.table)
        token = ensure_addon_token(session)
        self.client.get(f'/dine/?seller_id={self.seller_id}&s={token}')
        shop = f'/shop/?seller_id={self.seller_id}'
        self.client.post(shop, {
            'action': 'add_to_cart',
            'dish_id': self.dish.dish_id,
            'price_tier': 'general',
        })
        self.client.post(shop, {'action': 'checkout'})
        self.client.post('/place-order/', {
            'seller_id': self.seller_id,
            'fulfillment_type': CHANNEL_DINE_IN,
            'dine_in_at_shop': '1',
        })
        resp = self.client.get(shop)
        self.assertNotContains(resp, '请先选择下单方式')
        self.assertContains(resp, '当前桌台')

    def test_stale_table_session_shows_rescan_not_channel_pick(self):
        session, _ = open_table_main_session(self.table)
        token = ensure_addon_token(session)
        self.client.get(f'/dine/?seller_id={self.seller_id}&s={token}')
        close_table_session(session)
        resp = self.client.get(f'/shop/?seller_id={self.seller_id}')
        self.assertNotContains(resp, '请先选择下单方式')
        self.assertContains(resp, '重新扫描')

    def test_continue_dine_url_uses_addon_entry(self):
        session, _ = open_table_main_session(self.table)
        token = ensure_addon_token(session)
        url = build_table_continue_dine_url(self.seller_id, session)
        self.assertIn('s=', url)
        self.assertIn(token, url)


class WaiterTableBoardPhaseATests(TestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='wt_a_seller',
            password='seller-pass-123',
            shop_code='wta',
            shop_name='看板A阶段试验店',
        )
        self.seller_id = bundle.seller.username
        self.shop_code = bundle.shop.shop_code
        settings = get_operating_settings(self.seller_id)
        settings.plugin_dining_enabled = True
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=['plugin_dining_enabled', 'business_open', 'business_close'])
        self.table = ShopTable.objects.create(
            seller_id=self.seller_id,
            table_number='9',
            is_active=True,
        )
        self.waiter = User.objects.create_user(
            username=staff_internal_username(self.seller_id, '服务员A'),
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

    def test_busy_table_has_qr_data_url(self):
        open_table_main_session(self.table)
        from django.test import RequestFactory

        req = RequestFactory().get('/')
        ctx = build_waiter_table_board_context(self.seller_id, request=req)
        row = ctx['table_rows'][0]
        self.assertTrue(row['is_busy'])
        self.assertTrue(row['addon_qr_data_url'].startswith('data:image/png;base64,'))

    def test_waiter_close_empty_table(self):
        open_table_main_session(self.table)
        ok, msg = waiter_close_table(
            self.seller_id, self.table.table_id, operator=self.waiter,
        )
        self.assertTrue(ok)
        self.assertFalse(table_main_session_is_active(self.table))
        self.assertIn('翻台', msg)

    def test_waiter_close_table_via_post(self):
        open_table_main_session(self.table)
        url = reverse('shop_work', kwargs={'shop_code': self.shop_code})
        resp = self.client.post(
            f'{url}?view=waiter',
            {'waiter_close_table': '1', 'table_id': str(self.table.table_id)},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(table_main_session_is_active(self.table))

    def test_panel_shows_qr_and_close_button(self):
        open_table_main_session(self.table)
        url = reverse('shop_work', kwargs={'shop_code': self.shop_code})
        resp = self.client.get(f'{url}?view=waiter')
        self.assertContains(resp, 'data:image/png;base64,')
        self.assertContains(resp, '翻台关桌')
