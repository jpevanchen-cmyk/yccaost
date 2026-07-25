# 批次 G · G1-1：商品展示编号分配与删后不复用

from django.test import TestCase

from waimai.models import Dish, DishDisplayCodeOccupied, User
from waimai.product_display_code_helpers import (
    allocate_next_display_code,
    collect_taken_display_codes,
)


class ProductDisplayCodeTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='display_code_seller',
            password='test-pass',
            role='seller',
        )
        self.other_seller = User.objects.create_user(
            username='display_code_other',
            password='test-pass',
            role='seller',
        )

    def test_new_dish_gets_sequential_layer1_codes(self):
        first = Dish.objects.create(
            seller_id=self.seller.username,
            name='商品甲',
            price='10.00',
        )
        second = Dish.objects.create(
            seller_id=self.seller.username,
            name='商品乙',
            price='12.00',
        )
        self.assertEqual(first.display_code, 'a001')
        self.assertEqual(second.display_code, 'a002')

    def test_deleted_code_is_not_reused(self):
        dish = Dish.objects.create(
            seller_id=self.seller.username,
            name='待删商品',
            price='8.00',
        )
        self.assertEqual(dish.display_code, 'a001')
        dish.delete()
        self.assertTrue(
            DishDisplayCodeOccupied.objects.filter(
                seller_id=self.seller.username,
                display_code='a001',
            ).exists()
        )
        replacement = Dish.objects.create(
            seller_id=self.seller.username,
            name='新商品',
            price='9.00',
        )
        self.assertEqual(replacement.display_code, 'a002')
        taken = collect_taken_display_codes(self.seller.username)
        self.assertIn('a001', taken)
        self.assertEqual(allocate_next_display_code(self.seller.username), 'a003')

    def test_sellers_have_independent_code_pools(self):
        mine = Dish.objects.create(
            seller_id=self.seller.username,
            name='本店商品',
            price='5.00',
        )
        theirs = Dish.objects.create(
            seller_id=self.other_seller.username,
            name='他店商品',
            price='6.00',
        )
        self.assertEqual(mine.display_code, 'a001')
        self.assertEqual(theirs.display_code, 'a001')
