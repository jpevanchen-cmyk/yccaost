# A.11.12：默认商品清单 + 结算前清单校验

from datetime import time
from decimal import Decimal

from django.test import TestCase

from waimai.models import Dish, MenuProfile, MenuProfileItem, ShopProfile, User
from waimai.menu_helpers import (
    ensure_active_menu_catalog,
    get_active_menu_profile,
    sanitize_cart_for_active_catalog,
)
from waimai.operating_helpers import get_operating_settings
from waimai.order_helpers import cart_line_key, prepare_checkout_cart
from waimai.product_helpers import PRICE_TIER_GENERAL
from waimai.product_shell_helpers import build_product_shell, catalog_controls_shop_display


class MenuCatalogGuardTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='catalog_seller', password='seller-pass-123', role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='清单防护试验店',
            shop_code='catshop',
            address='试验地址',
        )
        settings = get_operating_settings(self.seller.username)
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=['business_open', 'business_close'])

    def test_ensure_creates_default_active_catalog(self):
        self.assertFalse(MenuProfile.objects.filter(seller_id=self.seller.username).exists())
        profile = ensure_active_menu_catalog(self.seller.username)
        word = build_product_shell(self.seller.username)['catalog_word']
        self.assertEqual(profile.name, f'{word} 1')
        settings = get_operating_settings(self.seller.username)
        self.assertEqual(settings.active_menu_profile_id, profile.profile_id)
        self.assertTrue(catalog_controls_shop_display(self.seller.username))

    def test_get_active_profile_auto_ensures(self):
        profile = get_active_menu_profile(self.seller.username)
        self.assertIsNotNone(profile)
        word = build_product_shell(self.seller.username)['catalog_word']
        self.assertEqual(profile.name, f'{word} 1')

    def test_ensure_activates_existing_profile_when_none_selected(self):
        orphan = MenuProfile.objects.create(
            seller_id=self.seller.username, name='商品列表 9',
        )
        settings = get_operating_settings(self.seller.username)
        settings.active_menu_profile = None
        settings.save(update_fields=['active_menu_profile'])
        profile = ensure_active_menu_catalog(self.seller.username)
        self.assertEqual(profile.profile_id, orphan.profile_id)

    def test_checkout_removes_item_not_on_active_catalog(self):
        profile = ensure_active_menu_catalog(self.seller.username)
        listed = Dish.objects.create(
            seller_id=self.seller.username, name='在清单', price=Decimal('10.00'), is_active=True,
        )
        hidden = Dish.objects.create(
            seller_id=self.seller.username, name='不在清单', price=Decimal('12.00'), is_active=True,
        )
        MenuProfileItem.objects.create(profile=profile, dish=listed, is_listed=True)
        MenuProfileItem.objects.create(profile=profile, dish=hidden, is_listed=False)

        cart = {
            cart_line_key(listed.dish_id, PRICE_TIER_GENERAL): 1,
            cart_line_key(hidden.dish_id, PRICE_TIER_GENERAL): 2,
        }
        cleaned, removed = sanitize_cart_for_active_catalog(cart, self.seller.username)
        self.assertIn(cart_line_key(listed.dish_id, PRICE_TIER_GENERAL), cleaned)
        self.assertNotIn(cart_line_key(hidden.dish_id, PRICE_TIER_GENERAL), cleaned)
        self.assertTrue(any('不在清单' in note for note in removed))

        cart, items, subtotal, notes = prepare_checkout_cart(cart, self.seller.username)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['dish'].dish_id, listed.dish_id)
        self.assertEqual(subtotal, Decimal('10.00'))
        self.assertTrue(notes)

    def test_checkout_removes_inactive_dish(self):
        profile = ensure_active_menu_catalog(self.seller.username)
        dish = Dish.objects.create(
            seller_id=self.seller.username, name='已下架商品', price=Decimal('8.00'), is_active=False,
        )
        MenuProfileItem.objects.create(profile=profile, dish=dish, is_listed=True)
        cart = {cart_line_key(dish.dish_id, PRICE_TIER_GENERAL): 1}
        cleaned, removed = sanitize_cart_for_active_catalog(cart, self.seller.username)
        self.assertEqual(cleaned, {})
        self.assertTrue(any('已下架' in note for note in removed))
