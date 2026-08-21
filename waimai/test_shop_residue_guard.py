# 店侧残留：禁销人号、禁同名注册领店

from datetime import time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from waimai.account_cancel_helpers import account_cancel_block_reason
from waimai.models import ShopDeliverySettings, ShopProfile
from waimai.operating_helpers import get_operating_settings
from waimai.shop_cancel_helpers import cancel_shop_for_owner
from waimai.shop_residue_helpers import username_has_shop_residue
from waimai.staff_account_helpers import validate_main_eco_username
from waimai.test_shop_helpers import create_test_shop_bundle

User = get_user_model()


class ShopResidueGuardTests(TestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='residue_seller',
            password='seller-pass-123',
            shop_code='residue',
            shop_name='残留护栏店',
            with_menu=True,
            with_dish=True,
            dish_name='护栏菜',
            dish_price=Decimal('5.00'),
        )
        self.seller = bundle.seller
        self.shop = bundle.shop
        ops = get_operating_settings(self.seller.username)
        ops.business_open = time(0, 0)
        ops.business_close = time(23, 59)
        ops.save()

    def test_soft_cancel_blocks_account_cancel(self):
        cancel_shop_for_owner(self.seller)
        self.shop.refresh_from_db()
        self.assertTrue(self.shop.cancelled_at)
        msg = account_cancel_block_reason(self.seller)
        self.assertIn('尚未彻底清理', msg)

    def test_orphan_delivery_blocks_register_same_name(self):
        ShopProfile.objects.filter(seller_id=self.seller.username).delete()
        ShopDeliverySettings.objects.get_or_create(seller_id=self.seller.username)
        self.assertTrue(ShopDeliverySettings.objects.filter(
            seller_id=self.seller.username,
        ).exists())
        self.assertTrue(username_has_shop_residue(self.seller.username))
        with self.assertRaises(ValidationError):
            validate_main_eco_username(self.seller.username)
