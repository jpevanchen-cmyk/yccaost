# 订单进度只读展示：后厨撤回备制不重复里程碑

from decimal import Decimal

from django.test import TestCase

from waimai.models import BuyOrder, User
from waimai.order_timeline_helpers import build_order_timeline
from waimai.kitchen_helpers import mark_kitchen_dish_unit_prepared, undo_kitchen_dish_unit_prepared


class OrderTimelineReadonlyTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='tl_ro_seller', password='x', role='seller',
        )
        self.operator = 'kitchen1'
        self.order = BuyOrder.objects.create(
            buyer_id='buyer_ro',
            seller_id=self.seller.username,
            total_amount=Decimal('10'),
            dish_items=[{
                'line_id': 'line-1',
                'dish_id': 'dish-ro-1',
                'name': '试验菜',
                'price': 10,
                'quantity': 1,
                'prepared_count': 0,
                'served_count': 0,
            }],
            payment_status='paid',
            order_status='awaiting_prep',
            fulfillment_type='delivery',
        )

    def test_prep_toggle_shows_at_most_one_prep_and_ready_milestone(self):
        dish_id = 'dish-ro-1'
        mark_kitchen_dish_unit_prepared(self.order, dish_id, operator_username=self.operator)
        self.order.refresh_from_db()
        undo_kitchen_dish_unit_prepared(self.order, dish_id, operator_username=self.operator)
        self.order.refresh_from_db()
        mark_kitchen_dish_unit_prepared(self.order, dish_id, operator_username=self.operator)
        self.order.refresh_from_db()

        labels = [lbl for lbl, _ in build_order_timeline(self.order, viewer='work')]
        self.assertEqual(labels.count('开始备货'), 1)
        self.assertEqual(labels.count('出餐可配送'), 1)
        self.assertEqual(self.order.order_status, 'ready_pickup')

        undo_kitchen_dish_unit_prepared(self.order, dish_id, operator_username=self.operator)
        self.order.refresh_from_db()
        labels2 = [lbl for lbl, _ in build_order_timeline(self.order, viewer='work')]
        self.assertEqual(labels2.count('开始备货'), 1)
        self.assertNotIn('出餐可配送', labels2)
        self.assertIsNone(self.order.ready_at)
