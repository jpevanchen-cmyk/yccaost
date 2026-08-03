# 80-2a 修复：Panel 刷新后清单下拉无法切换

from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from waimai.menu_helpers import ensure_active_menu_catalog
from waimai.models import Dish, MenuProfile, MenuProfileItem, ShopProfile, User
from waimai.panel_refresh_helpers import PANEL_REQUEST_HEADER


class PanelProfileSwitchAfterRefreshTests(TestCase):
    """模拟：先 Panel 刷新再 GET 换清单（下拉 listener 丢失场景的回归）"""

    def setUp(self):
        self.seller = User.objects.create_user(
            username='panel_sw_seller',
            password='pass12345',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='切换试验店',
            shop_code='swshop',
            address='试验地址',
        )
        self.profile_a = ensure_active_menu_catalog(self.seller.username)
        self.profile_a.name = '周一午餐'
        self.profile_a.save(update_fields=['name'])
        self.profile_b = MenuProfile.objects.create(
            seller_id=self.seller.username,
            name='周三菜单',
        )
        self.dish = Dish.objects.create(
            seller_id=self.seller.username,
            name='试验菜',
            price=Decimal('10.00'),
            is_active=True,
        )
        MenuProfileItem.objects.create(
            profile=self.profile_a, dish=self.dish, is_listed=True,
        )
        MenuProfileItem.objects.create(
            profile=self.profile_b, dish=self.dish, is_listed=True,
        )
        self.client = Client()
        self.client.login(username='panel_sw_seller', password='pass12345')
        self.products_url = reverse('seller_panel_section', kwargs={'section': 'products'})

    def test_switch_to_second_profile_after_panel_post(self):
        """先 POST 触发 Panel 刷新，再 GET 换另一清单，后端应返回对应 HTML"""
        item = MenuProfileItem.objects.get(profile=self.profile_a, dish=self.dish)
        self.client.post(
            self.products_url,
            {
                'toggle_menu_item_listed': '1',
                'profile_id': str(self.profile_a.profile_id),
                'item_id': str(item.item_id),
            },
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        resp = self.client.get(
            f'{self.products_url}?profile={self.profile_b.profile_id}',
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertIn('周三菜单', data['html'])
        self.assertIn('selected', data['html'])  # 下拉应选中周三
