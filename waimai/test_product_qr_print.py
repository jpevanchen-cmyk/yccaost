# G1-7：商品二维码批量打印页

from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from waimai.models import Dish, User
from waimai.operating_helpers import get_operating_settings
from waimai.product_qr_print_helpers import (
    QR_PRINT_MAX_NAME_CHARS,
    build_catalog_qr_print_cards,
    dish_name_fits_qr_print,
)
from waimai.menu_helpers import ensure_active_menu_catalog
from waimai.product_scan_helpers import build_product_scan_qr_rows


class ProductQrPrintTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='qr_print_seller',
            password='secret',
            role='seller',
        )
        self.client = Client()
        self.client.login(username='qr_print_seller', password='secret')
        self.dish = Dish.objects.create(
            seller_id=self.seller.username,
            name='短名',
            price=Decimal('10'),
            is_active=True,
            display_code='a001',
        )
        ensure_active_menu_catalog(self.seller.username)

    def test_name_fit_rule(self):
        self.assertTrue(dish_name_fits_qr_print('a' * QR_PRINT_MAX_NAME_CHARS))
        self.assertFalse(dish_name_fits_qr_print('a' * (QR_PRINT_MAX_NAME_CHARS + 1)))

    def test_build_cards_for_active_catalog(self):
        op = get_operating_settings(self.seller.username)
        op.table_lan_base_url = 'http://192.168.3.120:8000'
        op.save(update_fields=['table_lan_base_url'])
        request = self.client.get('/', HTTP_HOST='127.0.0.1:8000').wsgi_request
        cards = build_catalog_qr_print_cards(request, self.seller.username)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['display_code'], 'A001')
        self.assertTrue(cards[0]['tiers'])
        self.assertTrue(cards[0]['tiers'][0].get('data_url'))

    def test_product_qr_uses_lan_not_loopback(self):
        op = get_operating_settings(self.seller.username)
        op.table_lan_base_url = 'http://192.168.3.88:8000'
        op.save(update_fields=['table_lan_base_url'])
        request = self.client.get('/', HTTP_HOST='127.0.0.1:8000').wsgi_request
        rows = build_product_scan_qr_rows(request, self.dish, self.seller.username)
        self.assertTrue(rows)
        self.assertTrue(rows[0]['url'].startswith('http://192.168.3.88:8000/'))
        self.assertNotIn('127.0.0.1', rows[0]['url'])

    def test_product_qr_empty_when_no_lan_on_loopback(self):
        op = get_operating_settings(self.seller.username)
        op.table_lan_base_url = ''
        op.save(update_fields=['table_lan_base_url'])
        request = self.client.get('/', HTTP_HOST='127.0.0.1:8000').wsgi_request
        rows = build_product_scan_qr_rows(request, self.dish, self.seller.username)
        self.assertEqual(rows, [])
        cards = build_catalog_qr_print_cards(request, self.seller.username)
        self.assertEqual(cards, [])

    def test_print_page_renders(self):
        op = get_operating_settings(self.seller.username)
        op.table_lan_base_url = 'http://192.168.3.120:8000'
        op.save(update_fields=['table_lan_base_url'])
        url = reverse('seller_product_qr_print')
        resp = self.client.get(url, HTTP_HOST='127.0.0.1:8000')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'A001')
        self.assertContains(resp, '批量打印商品二维码')
