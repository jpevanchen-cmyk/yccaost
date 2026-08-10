# V1 桌台：专属加点码、禁止双开、空闲/启用中

from datetime import time

from urllib.parse import unquote

from django.test import Client, TransactionTestCase

from waimai.dine_models import ShopTable
from waimai.operating_helpers import get_operating_settings
from waimai.plugins.dining.table_helpers import (
    ADDON_TOKEN_INVALID_MSG,
    PHYSICAL_TABLE_BUSY_MSG,
    bind_addon_session,
    close_table_session,
    ensure_addon_token,
    get_open_main_session_for_table,
    open_table_main_session,
    table_main_session_is_active,
)
from waimai.test_shop_helpers import create_test_shop_bundle


class TableSessionV1Tests(TransactionTestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='v1_table_seller',
            password='seller-pass-123',
            shop_code='v1tbl',
            shop_name='V1桌台试验店',
        )
        self.seller_id = bundle.seller.username
        settings = get_operating_settings(self.seller_id)
        settings.plugin_dining_enabled = True
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=['plugin_dining_enabled', 'business_open', 'business_close'])
        self.table = ShopTable.objects.create(
            seller_id=self.seller_id,
            table_number='1',
            is_active=True,
        )
        self.client = Client()

    def test_open_main_session_creates_addon_token(self):
        session, err = open_table_main_session(self.table)
        self.assertEqual(err, '')
        self.assertIsNotNone(session)
        assert session is not None
        self.assertTrue(session.addon_token)
        self.assertTrue(table_main_session_is_active(self.table))

    def test_physical_double_open_blocked(self):
        first, _ = open_table_main_session(self.table)
        self.assertIsNotNone(first)
        second, err = open_table_main_session(self.table)
        self.assertIsNone(second)
        self.assertEqual(err, PHYSICAL_TABLE_BUSY_MSG)

    def test_bind_addon_after_open(self):
        session, _ = open_table_main_session(self.table)
        assert session is not None
        token = ensure_addon_token(session)
        bound, err = bind_addon_session(self.seller_id, token)
        self.assertEqual(err, '')
        self.assertEqual(bound.session_id, session.session_id)

    def test_addon_invalid_after_close(self):
        session, _ = open_table_main_session(self.table)
        assert session is not None
        token = ensure_addon_token(session)
        close_table_session(session)
        bound, err = bind_addon_session(self.seller_id, token)
        self.assertIsNone(bound)
        self.assertEqual(err, ADDON_TOKEN_INVALID_MSG)

    def test_dine_entry_physical_then_addon(self):
        url_open = f'/dine/?seller_id={self.seller_id}&t={self.table.qr_token}'
        resp = self.client.get(url_open)
        self.assertEqual(resp.status_code, 302)
        session = get_open_main_session_for_table(self.table)
        self.assertIsNotNone(session)
        assert session is not None
        token = ensure_addon_token(session)

        client2 = Client()
        resp_busy = client2.get(url_open)
        self.assertIn('error=', resp_busy.url)
        self.assertIn(PHYSICAL_TABLE_BUSY_MSG, unquote(resp_busy.url))

        url_addon = f'/dine/?seller_id={self.seller_id}&s={token}'
        resp_addon = client2.get(url_addon)
        self.assertEqual(resp_addon.status_code, 302)
        self.assertIn('/shop/', resp_addon.url)

    def test_same_browser_rebind_physical_when_already_open(self):
        url_open = f'/dine/?seller_id={self.seller_id}&t={self.table.qr_token}'
        self.client.get(url_open)
        resp = self.client.get(url_open)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/shop/', resp.url)
        self.assertNotIn('error=', resp.url)
