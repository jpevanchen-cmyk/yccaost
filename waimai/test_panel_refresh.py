# 进度 80-1：Panel 静默刷新 · 清单行内开关试点

from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from waimai.menu_helpers import ensure_active_menu_catalog
from waimai.models import BuyOrder, Dish, MenuProfile, MenuProfileItem, ShopProfile, User
from waimai.panel_refresh_helpers import PANEL_REQUEST_HEADER


class PanelRefreshMenuToggleTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='panel_seller',
            password='pass12345',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='Panel 试验店',
            shop_code='panelshop',
            address='试验地址',
        )
        self.profile = ensure_active_menu_catalog(self.seller.username)
        self.dish = Dish.objects.create(
            seller_id=self.seller.username,
            name='试验商品',
            price=Decimal('10.00'),
            is_active=True,
            member_price_enabled=True,
            special_price_enabled=True,
        )
        self.item = MenuProfileItem.objects.create(
            profile=self.profile,
            dish=self.dish,
            is_listed=True,
            general_price_listed=True,
            member_price_listed=True,
            special_price_listed=True,
        )
        self.client = Client()
        self.client.login(username='panel_seller', password='pass12345')
        self.products_url = reverse('seller_panel_section', kwargs={'section': 'products'})

    def _toggle_listed_payload(self):
        return {
            'toggle_menu_item_listed': '1',
            'profile_id': str(self.profile.profile_id),
            'item_id': str(self.item.item_id),
        }

    def test_toggle_without_panel_header_still_redirects(self):
        resp = self.client.post(self.products_url, self._toggle_listed_payload())
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_listed)

    def test_toggle_with_panel_header_returns_json_and_html(self):
        resp = self.client.post(
            self.products_url,
            self._toggle_listed_payload(),
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['panel_id'], 'menu-panel-body')
        self.assertIn('menu-item-table', data['html'])
        self.assertIn('在本清单已下架', data['message'])
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_listed)

    def test_member_toggle_fail_returns_panel_error_json(self):
        self.dish.member_price_enabled = False
        self.dish.save(update_fields=['member_price_enabled'])
        resp = self.client.post(
            self.products_url,
            {
                'toggle_menu_item_member': '1',
                'profile_id': str(self.profile.profile_id),
                'item_id': str(self.item.item_id),
            },
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data['ok'])
        self.assertIn('会员价', data['message'])

    def test_panel_get_profile_switch_returns_html(self):
        profile2 = MenuProfile.objects.create(
            seller_id=self.seller.username,
            name='试验清单二',
        )
        MenuProfileItem.objects.create(
            profile=profile2,
            dish=self.dish,
            is_listed=True,
            general_price_listed=True,
        )
        resp = self.client.get(
            f'{self.products_url}?profile={profile2.profile_id}',
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertIn('试验清单二', data['html'])

    def test_save_cap_with_panel_header(self):
        resp = self.client.post(
            self.products_url,
            {
                'save_menu_item_cap': '1',
                'profile_id': str(self.profile.profile_id),
                'item_id': str(self.item.item_id),
                'sales_cap': '50',
            },
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertIn('可售上限', data['message'])
        self.item.refresh_from_db()
        self.assertEqual(self.item.sales_cap, 50)

    def test_activate_profile_blocked_by_open_order_returns_message(self):
        profile2 = MenuProfile.objects.create(
            seller_id=self.seller.username,
            name='待用清单',
        )
        MenuProfileItem.objects.create(
            profile=profile2,
            dish=self.dish,
            is_listed=True,
        )
        BuyOrder.objects.create(
            buyer_id='guest',
            seller_id=self.seller.username,
            total_amount=Decimal('10.00'),
            dish_items=[],
            payment_status='pending_payment',
            order_status='created',
            fulfillment_type='order',
        )
        resp = self.client.post(
            self.products_url,
            {
                'activate_menu_profile': '1',
                'profile_id': str(profile2.profile_id),
            },
            HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER,
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data['ok'])
        self.assertIn('未结束订单', data['message'])
