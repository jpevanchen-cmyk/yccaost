# 后厨/服务员看板：预计出餐时间排序与分组

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from .time_helpers import now_local_wall

from waimai.models import BuyOrder, ShopProfile, User
from waimai.shop_work_helpers import build_kitchen_board_context, build_waiter_board_context


class WorkBoardSortTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='wbs_seller',
            password='pass12345',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='排序测试店',
            shop_code='wbssort',
            address='测试地址',
        )
        self.now = now_local_wall()

    def _make_order(self, *, fulfillment_type, eta_minutes, prepared=None, served=None, order_status='preparing'):
        items = [{
            'dish_id': 'd1',
            'name': '测试菜',
            'quantity': 2,
            'prepared_count': prepared if prepared is not None else 0,
            'served_count': served if served is not None else 0,
        }]
        return BuyOrder.objects.create(
            buyer_id='buyer1',
            seller_id=self.seller.username,
            total_amount=Decimal('20.00'),
            subtotal_amount=Decimal('20.00'),
            dish_items=items,
            payment_status='paid',
            payment_method='wechat_simulate',
            order_status=order_status,
            fulfillment_type=fulfillment_type,
            estimated_ready_at=self.now + timedelta(minutes=eta_minutes),
        )

    def test_kitchen_sort_allows_missing_eta_mixed_with_filled(self):
        """有预计时间与无预计时间的单混排时，不得因时区形态不同而崩。"""
        with_eta = self._make_order(fulfillment_type='takeaway', eta_minutes=10, prepared=0)
        no_eta = BuyOrder.objects.create(
            buyer_id='buyer1',
            seller_id=self.seller.username,
            total_amount=Decimal('20.00'),
            subtotal_amount=Decimal('20.00'),
            dish_items=[{
                'dish_id': 'd1',
                'name': '测试菜',
                'quantity': 1,
                'prepared_count': 0,
                'served_count': 0,
            }],
            payment_status='paid',
            payment_method='wechat_simulate',
            order_status='preparing',
            fulfillment_type='takeaway',
            estimated_ready_at=None,
        )
        rows = build_kitchen_board_context(self.seller.username)['orders']
        ids = [row['order'].pk for row in rows]
        self.assertIn(with_eta.pk, ids)
        self.assertIn(no_eta.pk, ids)
        self.assertLess(ids.index(with_eta.pk), ids.index(no_eta.pk))

    def test_kitchen_groups_by_fulfillment(self):
        self._make_order(fulfillment_type='delivery', eta_minutes=10)
        self._make_order(fulfillment_type='takeaway', eta_minutes=12)
        self._make_order(fulfillment_type='dine_in', eta_minutes=8)

        groups = build_kitchen_board_context(self.seller.username)['order_groups']
        self.assertEqual(len(groups), 3)
        self.assertEqual(groups[0]['key'], 'delivery')
        self.assertEqual(groups[0]['count'], 1)
        self.assertEqual(groups[1]['count'], 1)
        self.assertEqual(groups[2]['count'], 1)

    def test_kitchen_and_waiter_panels_use_multi_fold(self):
        """后厨/服务员 Tab 须允许多卡片同时展开。"""
        from django.template.loader import render_to_string
        from waimai.workbench_shell_helpers import build_workbench_shell

        shell = build_workbench_shell(self.seller.username)
        kitchen_ctx = build_kitchen_board_context(self.seller.username)
        kitchen_ctx.update({
            'can_operate': True,
            'workbench_shell': shell,
            'form_action': '',
        })
        kitchen_html = render_to_string('waimai/_shop_work_kitchen_panel.html', kitchen_ctx)
        self.assertIn('data-yc-fold-multi="1"', kitchen_html)

        waiter_ctx = build_waiter_board_context(self.seller.username)
        waiter_ctx.update({
            'can_operate': True,
            'workbench_shell': shell,
            'form_action': '',
            'shop_work_code': 'wbssort',
            'work_user': self.seller,
        })
        waiter_html = render_to_string('waimai/_shop_work_waiter_panel.html', waiter_ctx)
        self.assertIn('data-yc-fold-multi="1"', waiter_html)

    def test_waiter_sorts_by_eta_and_sinks_all_served(self):
        early = self._make_order(fulfillment_type='dine_in', eta_minutes=6, prepared=2, served=0)
        late = self._make_order(fulfillment_type='dine_in', eta_minutes=25, prepared=2, served=0)
        done = self._make_order(fulfillment_type='dine_in', eta_minutes=4, prepared=2, served=2)

        rows = build_waiter_board_context(self.seller.username)['orders']
        ids = [row['order'].pk for row in rows]
        self.assertEqual(ids.index(early.pk), 0)
        self.assertEqual(ids.index(late.pk), 1)
        self.assertEqual(ids.index(done.pk), 2)
