# 体验日清：留账号与客人资格，只拆体验店（该点的该测）

from decimal import Decimal

from django.test import TestCase

from waimai.experience_helpers import purge_experience_data
from waimai.models import BuyOrder, ShopProfile, User
from waimai.staff_account_helpers import create_owner_workbench_staff
from waimai.test_shop_helpers import create_official_experience_test_shop, create_test_shop_bundle


class ExperiencePurgeKeepsBuyerTests(TestCase):
    def test_keeps_account_strips_shop_and_old_seller_role(self):
        bundle = create_test_shop_bundle(
            username='exp_purge_owner',
            shop_code='exppurge1',
            shop_name='体验日清店',
            with_dish=True,
        )
        owner = bundle.seller
        owner.is_experience = True
        owner.is_permanent = False
        owner.role = 'seller'
        owner.save(update_fields=['is_experience', 'is_permanent', 'role'])
        create_owner_workbench_staff(owner, 'pass12345')
        BuyOrder.objects.create(
            seller_id=owner.username,
            buyer_id='someone',
            total_amount=Decimal('10.00'),
            dish_items=[],
        )

        official = create_official_experience_test_shop(shop_name='官方留存店')
        guest = User.objects.create_user(
            username='exp_purge_guest',
            password='pass12345',
            role='buyer',
        )
        guest.is_experience = True
        guest.is_permanent = False
        guest.save(update_fields=['is_experience', 'is_permanent'])
        kept_order = BuyOrder.objects.create(
            seller_id=official.seller.username,
            buyer_id=guest.username,
            total_amount=Decimal('8.00'),
            dish_items=[],
        )

        first = purge_experience_data()
        self.assertEqual(first['shops'], 1)
        self.assertGreaterEqual(first['staff'], 1)
        self.assertEqual(first['hats'], 1)
        self.assertEqual(first['orders'], 1)

        owner.refresh_from_db()
        self.assertTrue(User.objects.filter(pk=owner.pk).exists())
        self.assertEqual(owner.role, 'buyer')
        self.assertFalse(ShopProfile.objects.filter(seller_id=owner.username).exists())
        self.assertFalse(
            User.objects.filter(employer_seller_id=owner.username).exists(),
        )
        self.assertTrue(User.objects.filter(pk=guest.pk).exists())
        self.assertTrue(BuyOrder.objects.filter(order_id=kept_order.order_id).exists())
        self.assertTrue(ShopProfile.objects.filter(seller_id=official.seller.username).exists())

        second = purge_experience_data()
        self.assertEqual(second['shops'], 0)
        self.assertEqual(second['staff'], 0)
        self.assertEqual(second['hats'], 0)
        self.assertEqual(second['orders'], 0)

    def test_buyer_opened_shop_also_stripped(self):
        owner = User.objects.create_user(
            username='exp_purge_buyer_shop',
            password='pass12345',
            role='buyer',
        )
        owner.is_experience = True
        owner.is_permanent = False
        owner.save(update_fields=['is_experience', 'is_permanent'])
        ShopProfile.objects.create(
            seller_id=owner.username,
            shop_name='买家开的体验店',
            shop_code='exppurge2',
            address='体验地址',
        )

        purge_experience_data()
        owner.refresh_from_db()
        self.assertEqual(owner.role, 'buyer')
        self.assertFalse(ShopProfile.objects.filter(seller_id=owner.username).exists())
