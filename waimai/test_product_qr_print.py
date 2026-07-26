# G1-7：商品二维码批量打印页

from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from waimai.models import Dish, User
from waimai.product_qr_print_helpers import (
    QR_PRINT_MAX_NAME_CHARS,
    build_catalog_qr_print_cards,
    dish_name_fits_qr_print,
)
from waimai.menu_helpers import ensure_active_menu_catalog


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
        request = self.client.get('/').wsgi_request
        cards = build_catalog_qr_print_cards(request, self.seller.username)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['display_code'], 'A001')
        self.assertTrue(cards[0]['tiers'])

    def test_print_page_renders(self):
        url = reverse('seller_product_qr_print')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'A001')
        self.assertContains(resp, '批量打印商品二维码')
