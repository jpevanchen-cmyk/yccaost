# 进度 80-3：商品图管理 Panel + 营业开关 Panel

from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from waimai.models import Dish, ShopProfile, User
from waimai.operating_helpers import get_operating_settings
from waimai.panel_refresh_helpers import PANEL_REQUEST_HEADER
from waimai.product_image_helpers import apply_dish_image_uploads
from waimai.product_image_panel_helpers import product_image_manage_panel_id


def _make_png_upload(name='t.png'):
    # 最小合法 PNG
    raw = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f'
        b'\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    return SimpleUploadedFile(name, raw, content_type='image/png')


class ProductImagePanelTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='img_panel_seller',
            password='pass12345',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='图片 Panel 店',
            shop_code='imgpanel',
            address='试验地址',
        )
        self.dish = Dish.objects.create(
            seller_id=self.seller.username,
            name='带图商品',
            price=Decimal('8.00'),
            is_active=True,
            display_code='a101',
        )
        apply_dish_image_uploads(self.dish, [_make_png_upload('a.png'), _make_png_upload('b.png')])
        self.client = Client()
        self.client.login(username='img_panel_seller', password='pass12345')
        self.products_url = reverse('seller_panel_section', kwargs={'section': 'products'})
        self.panel_id = product_image_manage_panel_id(self.dish)

    def test_delete_image_panel_returns_html(self):
        first = self.dish.product_images.order_by('sort_index').first()
        resp = self.client.post(
            self.products_url,
            {
                'delete_dish_image': '1',
                'dish_id': str(self.dish.dish_id),
                'image_id': str(first.image_id),
                'idempotency_key': 'img-del-001',
            },
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['panel_id'], self.panel_id)
        self.assertIn('product-image-manage-block', data['html'])
        self.assertEqual(self.dish.product_images.count(), 1)

    def test_delete_without_panel_still_redirects(self):
        first = self.dish.product_images.order_by('sort_index').first()
        resp = self.client.post(
            self.products_url,
            {
                'delete_dish_image': '1',
                'dish_id': str(self.dish.dish_id),
                'image_id': str(first.image_id),
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.dish.product_images.count(), 1)


class OperatingStatusPanelTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='op_panel_seller',
            password='pass12345',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='营业 Panel 店',
            shop_code='oppanel',
            address='试验地址',
        )
        self.client = Client()
        self.client.login(username='op_panel_seller', password='pass12345')
        self.url = reverse('seller_panel_section', kwargs={'section': 'operating'})

    def test_toggle_open_panel_returns_html(self):
        settings = get_operating_settings(self.seller.username)
        self.assertFalse(settings.closed_for_today)
        resp = self.client.post(
            self.url,
            {'toggle_open': '1', 'idempotency_key': 'op-toggle-001'},
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['panel_id'], 'operating-status-panel')
        self.assertIn('停止营业', data['html'])
        settings.refresh_from_db()
        self.assertTrue(settings.closed_for_today)

    def test_toggle_open_idempotent_same_key(self):
        resp1 = self.client.post(
            self.url,
            {'toggle_open': '1', 'idempotency_key': 'op-toggle-same'},
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        resp2 = self.client.post(
            self.url,
            {'toggle_open': '1', 'idempotency_key': 'op-toggle-same'},
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        settings = get_operating_settings(self.seller.username)
        # 同一幂等键只切换一次，仍为停止营业
        self.assertTrue(settings.closed_for_today)

    def test_panel_without_toggle_returns_plain_fail(self):
        """静默刷新漏掉动作名时须白话失败，勿整页 HTML。"""
        resp = self.client.post(
            self.url,
            {'idempotency_key': 'op-missing-action'},
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data['ok'])
        self.assertIn('切换营业', data['message'])
        settings = get_operating_settings(self.seller.username)
        self.assertFalse(settings.closed_for_today)

    def test_operating_page_has_hidden_toggle_marker(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8')
        self.assertIn('name="toggle_open"', html)
        self.assertIn('type="hidden"', html)
