# 服务员工作台 · 桌台看板

from datetime import time

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse

from waimai.dine_models import ShopTable
from waimai.operating_helpers import get_operating_settings
from waimai.plugins.dining.table_helpers import (
    open_table_main_session,
    table_main_session_is_active,
)
from waimai.plugins.dining.waiter_table_helpers import build_waiter_table_board_context
from waimai.shop_work_auth import establish_shop_work_session
from waimai.shop_work_helpers import build_waiter_board_context
from waimai.staff_account_helpers import PERM_DINING_WAITER, staff_internal_username
from waimai.test_shop_helpers import create_test_shop_bundle
from waimai.workbench_shell_helpers import build_workbench_shell

User = get_user_model()


class WaiterTableBoardContextTests(TestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='wt_board_seller',
            password='seller-pass-123',
            shop_code='wtboard',
            shop_name='桌台看板试验店',
        )
        self.seller_id = bundle.seller.username
        self.shop_code = bundle.shop.shop_code
        settings = get_operating_settings(self.seller_id)
        settings.plugin_dining_enabled = True
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=['plugin_dining_enabled', 'business_open', 'business_close'])
        self.table_idle = ShopTable.objects.create(
            seller_id=self.seller_id,
            table_number='1',
            is_active=True,
        )
        self.table_busy = ShopTable.objects.create(
            seller_id=self.seller_id,
            table_number='2',
            is_active=True,
        )
        open_table_main_session(self.table_busy)
        self.waiter = User.objects.create_user(
            username=staff_internal_username(self.seller_id, '服务员桌台'),
            password='waiter-pass-123',
            role='staff',
            employer_seller_id=self.seller_id,
            staff_account_type='employee',
            staff_job_title='服务员',
            staff_permissions=[PERM_DINING_WAITER],
        )

    def test_hidden_when_dining_plugin_off(self):
        settings = get_operating_settings(self.seller_id)
        settings.plugin_dining_enabled = False
        settings.save(update_fields=['plugin_dining_enabled'])
        ctx = build_waiter_table_board_context(self.seller_id)
        self.assertFalse(ctx['show_table_board'])
        self.assertEqual(ctx['table_rows'], [])

    def test_rows_show_idle_and_busy(self):
        ctx = build_waiter_table_board_context(
            self.seller_id, shop_code=self.shop_code,
        )
        self.assertTrue(ctx['show_table_board'])
        self.assertEqual(len(ctx['table_rows']), 2)
        idle = next(r for r in ctx['table_rows'] if r['table_number'] == '1')
        busy = next(r for r in ctx['table_rows'] if r['table_number'] == '2')
        self.assertFalse(idle['is_busy'])
        self.assertEqual(idle['state_label'], '空闲')
        self.assertTrue(idle['can_open'])
        self.assertEqual(idle['addon_scan_path'], '')
        self.assertTrue(busy['is_busy'])
        self.assertEqual(busy['state_label'], '启用')
        self.assertFalse(busy['can_open'])
        self.assertIn('/dine/?', busy['addon_scan_path'])
        self.assertIn('s=', busy['addon_scan_path'])
        self.assertIn('/work/table/', busy['order_url'])

    def test_waiter_board_context_includes_table_board(self):
        ctx = build_waiter_board_context(self.seller_id)
        self.assertTrue(ctx['show_table_board'])
        self.assertEqual(len(ctx['table_rows']), 2)

    def test_panel_template_renders_open_and_addon(self):
        from django.test import RequestFactory

        req = RequestFactory().get('/')
        ctx = build_waiter_board_context(self.seller_id, request=req)
        ctx.update({
            'can_operate': True,
            'form_action': f'/s/{self.shop_code}/work/?view=waiter',
            'workbench_shell': build_workbench_shell(self.seller_id),
        })
        html = render_to_string('waimai/_shop_work_waiter_panel.html', ctx)
        self.assertIn('桌台看板', html)
        self.assertIn('代客开台并点菜', html)
        self.assertIn('帮此桌点餐', html)
        self.assertIn('翻台关桌', html)
        self.assertIn('waiter-table-tile', html)
        self.assertIn('data:image/png;base64,', html)
        self.assertIn('空闲', html)
        self.assertIn('启用', html)
        self.assertIn('waiter_open_table', html)


class WaiterTableBoardPostTests(TestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='wt_post_seller',
            password='seller-pass-123',
            shop_code='wtpost',
            shop_name='桌台开台POST试验店',
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
            table_number='8',
            is_active=True,
        )
        self.waiter = User.objects.create_user(
            username=staff_internal_username(self.seller_id, '服务员开台'),
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

    def test_waiter_open_table_via_post(self):
        url = f'{self._work_url()}?view=waiter'
        resp = self.client.post(url, {
            'waiter_open_table': '1',
            'table_id': str(self.table.table_id),
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f'/s/{self.shop_code}/work/table/', resp['Location'])
        self.assertIn(str(self.table.table_id), resp['Location'])
        self.assertTrue(table_main_session_is_active(self.table))

    def test_waiter_open_busy_table_rejected(self):
        open_table_main_session(self.table)
        url = f'{self._work_url()}?view=waiter'
        resp = self.client.post(url, {
            'waiter_open_table': '1',
            'table_id': str(self.table.table_id),
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(table_main_session_is_active(self.table))

    def test_waiter_page_contains_table_board(self):
        url = f'{self._work_url()}?view=waiter'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '桌台看板')
        self.assertContains(resp, '代客开台并点菜')
        self.assertContains(resp, '帮此桌点餐')
