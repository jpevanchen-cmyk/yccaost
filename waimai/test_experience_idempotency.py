# 幂等第 11 步：体验引导写操作防重复

from decimal import Decimal

from django.test import Client, TestCase

from waimai.menu_helpers import get_active_menu_profile
from waimai.models import Dish, MenuProfile, ShopTable
from waimai.onboarding.demo_cleanup import DEMO_DISH_NAME, cleanup_experience_demo_data
from waimai.onboarding.official_shop import OFFICIAL_SHOP_NAME
from waimai.test_shop_helpers import create_official_experience_test_shop


class ExperienceWriteIdempotencyTests(TestCase):
    def setUp(self):
        bundle = create_official_experience_test_shop(shop_name=OFFICIAL_SHOP_NAME)
        self.seller = bundle.seller
        self.client = Client()
        self.products_url = '/experience/preview/seller/products/'
        self.dine_url = '/experience/preview/seller/dine/'
        self.exp_fields = {
            'exp': '1',
            'exp_track': 'seller',
            'exp_major': '2',
            'exp_micro': '12',
        }

    def tearDown(self):
        cleanup_experience_demo_data(self.seller.username)

    def test_same_key_create_menu_one_profile(self):
        active = get_active_menu_profile(self.seller.username)
        key = 'exp-menu-key-00000001'
        payload = {
            **self.exp_fields,
            'create_menu_profile': '1',
            'profile_name': '幂等演示清单',
            'copy_from_profile_id': str(active.profile_id),
            'experience_menu_ajax': '1',
            'idempotency_key': key,
        }
        headers = {'HTTP_X_EXPERIENCE_MENU_AJAX': '1'}

        resp1 = self.client.post(self.products_url, payload, **headers)
        resp2 = self.client.post(self.products_url, payload, **headers)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        data1 = resp1.json()
        data2 = resp2.json()
        self.assertTrue(data1.get('ok'), data1)
        self.assertTrue(data2.get('ok'), data2)
        self.assertEqual(
            MenuProfile.objects.filter(seller_id=self.seller.username, name='幂等演示清单').count(),
            1,
        )

    def test_same_key_add_dish_one_record(self):
        key = 'exp-dish-key-00000001'
        name = '幂等演示商品'
        payload = {
            **self.exp_fields,
            'add_dish': '1',
            'name': name,
            'price': '88',
            'sort_order': '0',
            'list_on_all_menus': '1',
            'experience_product_ajax': '1',
            'idempotency_key': key,
        }
        headers = {'HTTP_X_EXPERIENCE_PRODUCT_AJAX': '1'}

        resp1 = self.client.post(self.products_url, payload, **headers)
        resp2 = self.client.post(self.products_url, payload, **headers)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp1.json()['ok'])
        self.assertTrue(resp2.json()['ok'])
        self.assertEqual(
            Dish.objects.filter(seller_id=self.seller.username, name=name).count(),
            1,
        )
        self.assertNotEqual(name, DEMO_DISH_NAME)

    def test_same_key_add_table_one_batch(self):
        key = 'exp-table-key-00000001'
        payload = {
            'add_table': '1',
            'table_min': '91',
            'table_max': '92',
            'exp': '1',
            'exp_track': 'seller',
            'exp_major': '7',
            'exp_micro': '20',
            'idempotency_key': key,
        }

        before = ShopTable.objects.filter(seller_id=self.seller.username).count()
        resp1 = self.client.post(self.dine_url, payload, follow=True)
        resp2 = self.client.post(self.dine_url, payload, follow=True)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        after = ShopTable.objects.filter(seller_id=self.seller.username).count()
        self.assertEqual(after - before, 2)
        self.assertTrue(
            ShopTable.objects.filter(seller_id=self.seller.username, table_number='91').exists(),
        )
