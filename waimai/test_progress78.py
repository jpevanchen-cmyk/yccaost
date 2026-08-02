# 进度 78：清单三档展示开关 · 补通用价

from datetime import time
from decimal import Decimal

from django.test import TestCase

from waimai.models import Dish, MenuProfileItem, ShopProfile, User
from waimai.menu_helpers import (
    dish_visible_on_shop,
    ensure_active_menu_catalog,
    get_shop_dishes_for_sale,
    menu_item_allows_tier,
    menu_item_has_visible_tier,
    sanitize_cart_for_active_catalog,
    sync_new_dish_to_menu_profiles,
)
from waimai.operating_helpers import get_operating_settings
from waimai.order_helpers import cart_line_key
from waimai.product_helpers import (
    PRICE_TIER_GENERAL,
    PRICE_TIER_MEMBER,
    PRICE_TIER_SPECIAL,
    build_dish_tier_options,
    validate_tier_purchase,
)
from waimai.product_scan_helpers import scan_tier_listed_on_shop


class MenuGeneralPriceListedTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='tier78_seller', password='seller-pass-123', role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='三档展示试验店',
            shop_code='tier78',
            address='试验地址',
        )
        settings = get_operating_settings(self.seller.username)
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=['business_open', 'business_close'])
        self.profile = ensure_active_menu_catalog(self.seller.username)
        self.dish = Dish.objects.create(
            seller_id=self.seller.username,
            name='试验菜',
            price=Decimal('10.00'),
            member_price_enabled=True,
            member_price_mode='fixed',
            member_price_fixed=Decimal('8.00'),
            special_price_enabled=True,
            special_price_mode='fixed',
            special_price_fixed=Decimal('6.00'),
            is_active=True,
        )
        sync_new_dish_to_menu_profiles(self.dish)
        self.menu_item = MenuProfileItem.objects.get(profile=self.profile, dish=self.dish)
        self.menu_item.is_listed = True
        self.menu_item.save(update_fields=['is_listed'])

    def test_general_price_listed_defaults_true(self):
        self.assertTrue(self.menu_item.general_price_listed)

    def test_menu_item_allows_tier_respects_general_flag(self):
        self.menu_item.general_price_listed = False
        self.menu_item.save(update_fields=['general_price_listed'])
        self.assertFalse(
            menu_item_allows_tier(self.menu_item, PRICE_TIER_GENERAL, self.seller.username),
        )
        self.assertTrue(
            menu_item_allows_tier(self.menu_item, PRICE_TIER_MEMBER, self.seller.username),
        )

    def test_build_dish_tier_options_hides_general_when_not_listed(self):
        self.menu_item.general_price_listed = False
        self.menu_item.save(update_fields=['general_price_listed'])
        tiers = [opt['tier'] for opt in build_dish_tier_options(
            self.dish, None, self.seller.username, {},
        )]
        self.assertNotIn(PRICE_TIER_GENERAL, tiers)
        self.assertIn(PRICE_TIER_MEMBER, tiers)
        self.assertIn(PRICE_TIER_SPECIAL, tiers)

    def test_validate_tier_purchase_blocks_hidden_general(self):
        self.menu_item.general_price_listed = False
        self.menu_item.save(update_fields=['general_price_listed'])
        ok, reason = validate_tier_purchase(
            self.dish, PRICE_TIER_GENERAL, None, self.seller.username, 1, {},
        )
        self.assertFalse(ok)
        self.assertIn('未开放', reason)

    def test_sanitize_cart_removes_hidden_general_line(self):
        self.menu_item.general_price_listed = False
        self.menu_item.save(update_fields=['general_price_listed'])
        line_key = cart_line_key(self.dish.dish_id, PRICE_TIER_GENERAL)
        cart = {line_key: 2}
        cleaned, removed = sanitize_cart_for_active_catalog(cart, self.seller.username)
        self.assertNotIn(line_key, cleaned)
        self.assertTrue(removed)

    def test_scan_tier_allowed_follows_general_flag(self):
        self.menu_item.general_price_listed = False
        self.menu_item.save(update_fields=['general_price_listed'])
        self.assertFalse(
            scan_tier_listed_on_shop(self.dish, PRICE_TIER_GENERAL, self.seller.username),
        )
        self.assertTrue(
            scan_tier_listed_on_shop(self.dish, PRICE_TIER_MEMBER, self.seller.username),
        )

    def test_all_tiers_hidden_guest_cannot_see_dish(self):
        self.menu_item.general_price_listed = False
        self.menu_item.member_price_listed = False
        self.menu_item.special_price_listed = False
        self.menu_item.save(update_fields=[
            'general_price_listed', 'member_price_listed', 'special_price_listed',
        ])
        self.assertFalse(menu_item_has_visible_tier(self.menu_item, self.seller.username))
        self.assertFalse(dish_visible_on_shop(self.seller.username, self.dish.dish_id))
        dishes, _ = get_shop_dishes_for_sale(self.seller.username)
        self.assertNotIn(self.dish.dish_id, [d.dish_id for d in dishes])
        # 方案 A：本清单上架开关不因全关价而自动改
        self.menu_item.refresh_from_db()
        self.assertTrue(self.menu_item.is_listed)

    def test_one_tier_visible_guest_can_see_again(self):
        self.menu_item.general_price_listed = False
        self.menu_item.member_price_listed = False
        self.menu_item.special_price_listed = False
        self.menu_item.save(update_fields=[
            'general_price_listed', 'member_price_listed', 'special_price_listed',
        ])
        self.menu_item.member_price_listed = True
        self.menu_item.save(update_fields=['member_price_listed'])
        self.assertTrue(dish_visible_on_shop(self.seller.username, self.dish.dish_id))
        dishes, _ = get_shop_dishes_for_sale(self.seller.username)
        self.assertIn(self.dish.dish_id, [d.dish_id for d in dishes])
