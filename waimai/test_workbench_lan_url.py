# 工作台登录链接优先用局域网根地址（禁止用 127 冒充店内可扫地址）

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from waimai.operating_helpers import get_operating_settings, resolve_shop_access_base_url
from waimai.test_shop_helpers import create_test_shop_bundle


class ShopAccessBaseUrlTests(TestCase):
    def setUp(self):
        self.bundle = create_test_shop_bundle(username='lan_wb_boss')
        self.seller_id = self.bundle.seller.username
        self.client = Client()
        self.client.force_login(self.bundle.seller)

    def test_resolve_prefers_table_lan_over_request_loopback(self):
        op = get_operating_settings(self.seller_id)
        op.table_lan_base_url = 'http://192.168.3.120:8000'
        op.save(update_fields=['table_lan_base_url'])
        req = self.client.get('/').wsgi_request
        # 模拟本机用 127 打开
        req.META['HTTP_HOST'] = '127.0.0.1:8000'
        base = resolve_shop_access_base_url(req, self.seller_id)
        self.assertEqual(base, 'http://192.168.3.120:8000')

    def test_workbench_page_uses_lan_in_link(self):
        op = get_operating_settings(self.seller_id)
        op.table_lan_base_url = 'http://192.168.3.120:8000'
        op.save(update_fields=['table_lan_base_url'])
        code = self.bundle.shop.shop_code
        resp = self.client.get(
            reverse('seller_panel_section', kwargs={'section': 'workbench'}),
            HTTP_HOST='127.0.0.1:8000',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'http://192.168.3.120:8000/s/{code}/work/')
        self.assertNotContains(resp, f'http://127.0.0.1:8000/s/{code}/work/')

    def test_workbench_missing_lan_shows_plain_hint(self):
        op = get_operating_settings(self.seller_id)
        op.table_lan_base_url = ''
        op.save(update_fields=['table_lan_base_url'])
        resp = self.client.get(
            reverse('seller_panel_section', kwargs={'section': 'workbench'}),
            HTTP_HOST='127.0.0.1:8000',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '还没有可用的店内局域网地址')
