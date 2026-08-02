# 工牌与主账号查重分线（进度 83 补丁）

from django.test import TestCase

from waimai.forms import BuyerRegistrationForm, CreateStaffAccountForm
from waimai.models import ShopProfile, User
from waimai.staff_account_helpers import (
    main_eco_account_username_taken,
    staff_internal_username,
    staff_username_taken,
)


class AccountUsernameValidationTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='owner_a',
            password='pass1234',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='A店',
            shop_type='restaurant',
            address='测试路',
            shop_code='owna',
            is_listed=True,
        )
        User.objects.create_user(
            username=staff_internal_username('owner_a', '店员1'),
            password='pass1234',
            role='staff',
            employer_seller_id='owner_a',
        )

    def test_main_account_does_not_see_staff_internal_name_as_taken(self):
        self.assertFalse(main_eco_account_username_taken('店员1'))

    def test_main_account_still_blocks_duplicate_seller(self):
        self.assertTrue(main_eco_account_username_taken('owner_a'))

    def test_staff_can_use_same_display_name_as_seller(self):
        self.assertFalse(staff_username_taken('owner_a', 'owner_a'))
        form = CreateStaffAccountForm(
            {
                'username': 'owner_a',
                'password1': 'BadgePass123!',
                'password2': 'BadgePass123!',
                'account_type': 'management',
                'job_title': '店主工牌',
                'permissions': ['orders.view'],
            },
            seller_id='owner_a',
            account_type='management',
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_staff_display_name_duplicate_in_same_shop_blocked(self):
        form = CreateStaffAccountForm(
            {
                'username': '店员1',
                'password1': 'BadgePass123!',
                'password2': 'BadgePass123!',
                'account_type': 'employee',
                'job_title': '店员',
                'permissions': ['orders.view'],
            },
            seller_id='owner_a',
            account_type='employee',
        )
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)

    def test_buyer_register_not_blocked_by_staff_internal_username(self):
        form = BuyerRegistrationForm({
            'username': 'newbuyer',
            'password1': 'BuyerPass123!',
            'password2': 'BuyerPass123!',
        })
        self.assertTrue(form.is_valid(), form.errors)
