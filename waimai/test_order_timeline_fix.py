# 订单时间线展示规则修复（预计出餐位置、外卖交付节点）

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from waimai.models import BuyOrder, DeliveryOrder, User
from waimai.order_timeline_helpers import build_order_timeline


class OrderTimelineFixTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='tl_seller', password='x', role='seller',
        )

    def test_cod_completed_hides_estimated_ready_at_bottom(self):
        """货到付款完成后，不应再把「预计出餐」插到时间线末尾。"""
        base = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        order = BuyOrder.objects.create(
            buyer_id='buyer1',
            seller_id=self.seller.username,
            total_amount=Decimal('30'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            estimated_ready_at=base - timedelta(minutes=7),
            preparing_at=base,
            payment_time=base + timedelta(minutes=21),
            completed_at=base + timedelta(minutes=30),
        )
        DeliveryOrder.objects.create(
            buy_order=order,
            delivery_fee=Decimal('3'),
            distance_km=Decimal('1.0'),
            pickup_address='店',
            delivery_address='客',
            delivery_status='completed',
            estimated_delivery_time=base + timedelta(minutes=20),
            picked_up_at=base + timedelta(minutes=15),
            completed_at=base + timedelta(minutes=25),
        )

        rows = build_order_timeline(order, viewer='buyer')
        labels = [lbl for lbl, _ in rows]
        self.assertNotIn('预计出餐', labels)
        self.assertNotIn('预计送达', labels)
        # 已支付应排在取餐/送达附近，而非整段最后
        pay_idx = labels.index('已支付')
        pick_idx = labels.index('骑手已取餐')
        self.assertLess(pay_idx, len(labels) - 1)
        self.assertGreater(pay_idx, pick_idx - 2)

    def test_delivery_hides_goods_delivered_before_pickup(self):
        """外卖：骑手取餐前不展示「商品已全部交付」。"""
        now = timezone.now()
        order = BuyOrder.objects.create(
            buyer_id='buyer2',
            seller_id=self.seller.username,
            total_amount=Decimal('20'),
            dish_items=[],
            payment_status='paid',
            order_status='preparing',
            fulfillment_type='delivery',
            estimated_ready_at=now + timedelta(minutes=10),
            goods_delivered_at=now + timedelta(minutes=5),
        )
        DeliveryOrder.objects.create(
            buy_order=order,
            delivery_fee=Decimal('3'),
            distance_km=Decimal('1.0'),
            pickup_address='店',
            delivery_address='客',
            delivery_status='accepted',
            estimated_delivery_time=now + timedelta(minutes=30),
        )

        labels = [lbl for lbl, _ in build_order_timeline(order, viewer='work')]
        self.assertNotIn('商品已全部交付', labels)

        order.delivery_order.picked_up_at = now + timedelta(minutes=12)
        order.delivery_order.save(update_fields=['picked_up_at'])
        labels2 = [lbl for lbl, _ in build_order_timeline(order, viewer='work')]
        self.assertIn('商品已全部交付', labels2)

    def test_preparing_shows_estimated_ready_sorted(self):
        """备餐中仍显示预计出餐，且按时间排序。"""
        now = timezone.now()
        order = BuyOrder.objects.create(
            buyer_id='buyer3',
            seller_id=self.seller.username,
            total_amount=Decimal('15'),
            dish_items=[],
            payment_status='paid',
            order_status='preparing',
            fulfillment_type='delivery',
            estimated_ready_at=now + timedelta(minutes=8),
            preparing_at=now,
        )

        rows = build_order_timeline(order, viewer='seller')
        labels = [lbl for lbl, _ in rows]
        self.assertIn('预计出餐', labels)
        est_idx = labels.index('预计出餐')
        prep_idx = labels.index('开始备货')
        self.assertGreater(est_idx, prep_idx)

    def test_delivering_hides_estimated_ready_label(self):
        """配送中不再展示「预计出餐」类标签。"""
        now = timezone.now()
        order = BuyOrder.objects.create(
            buyer_id='buyer4',
            seller_id=self.seller.username,
            total_amount=Decimal('25'),
            dish_items=[],
            payment_status='paid',
            order_status='delivering',
            fulfillment_type='delivery',
            estimated_ready_at=now + timedelta(minutes=5),
        )
        self.assertFalse(order.should_show_estimated_ready_at())

    def test_order_history_hides_estimated_when_delivering(self):
        """买家订单列表：配送中不显示预计出餐徽章。"""
        from django.template.loader import render_to_string

        now = timezone.now()
        order = BuyOrder.objects.create(
            buyer_id='hist_deliver',
            seller_id=self.seller.username,
            total_amount=Decimal('30'),
            dish_items=[],
            payment_status='paid',
            order_status='delivering',
            fulfillment_type='delivery',
            estimated_ready_at=now + timedelta(minutes=6),
        )
        html = render_to_string('waimai/order_history.html', {
            'order_rows': [{
                'order': order,
                'shop_name': '试验店',
                'unread_msg_count': 0,
            }],
        })
        self.assertNotIn('预计', html)

    def test_shop_work_order_hides_estimated_when_delivering(self):
        """工作台订单页：配送中不显示预计出餐。"""
        from django.template.loader import render_to_string

        now = timezone.now()
        order = BuyOrder.objects.create(
            buyer_id='work_buyer',
            seller_id=self.seller.username,
            total_amount=Decimal('30'),
            dish_items=[],
            payment_status='paid',
            order_status='delivering',
            fulfillment_type='delivery',
            estimated_ready_at=now + timedelta(minutes=4),
        )
        html = render_to_string('waimai/shop_work_order.html', {
            'order': order,
            'work_user': self.seller,
            'back_url': '/s/test/work/',
            'workbench_shell': {'show_table_on_board': False, 'table_caption': '桌号'},
        })
        self.assertNotIn('预计', html)

    def test_kitchen_board_hides_estimated_when_all_prepared(self):
        """后厨看板：全部备好时不显示预计出餐。"""
        from django.template.loader import render_to_string
        from waimai.kitchen_helpers import build_kitchen_dish_rows
        from waimai.workbench_shell_helpers import build_workbench_shell

        now = timezone.now()
        order = BuyOrder.objects.create(
            buyer_id='kit_buyer',
            seller_id=self.seller.username,
            total_amount=Decimal('40'),
            dish_items=[{
                'dish_id': 'd1', 'name': '炒饭', 'quantity': 4, 'price': 10,
                'prepared_count': 4, 'prepared_qty': 4,
            }],
            payment_status='paid',
            order_status='preparing',
            fulfillment_type='delivery',
            estimated_ready_at=now + timedelta(minutes=30),
        )
        DeliveryOrder.objects.create(
            buy_order=order,
            rider_id='r1',
            delivery_fee=Decimal('2'),
            distance_km=Decimal('1'),
            pickup_address='店',
            delivery_address='客',
            delivery_status='accepted',
        )
        html = render_to_string('waimai/_shop_work_kitchen_panel.html', {
            'orders': [{
                'order': order,
                'phase_label': '已备好',
                'dish_rows': build_kitchen_dish_rows(order),
                'can_mark_all_prepared': False,
                'can_adjust_wait_time': True,
                'can_start_preparing': False,
                'can_dispatch': False,
                'can_reassign': False,
                'rider_id': 'r1',
                'log_lines': [],
            }],
            'summary_rows': [],
            'can_operate': True,
            'workbench_shell': build_workbench_shell(self.seller.username),
            'dispatch_riders': [],
            'form_action': '',
        })
        self.assertNotIn('预计', html)

    def test_waiter_board_hides_estimated_when_handed_to_rider(self):
        """服务员看板：全部交给骑手时不显示预计出餐。"""
        from django.template.loader import render_to_string
        from waimai.order_progress_helpers import build_dual_progress_groups
        from waimai.workbench_shell_helpers import build_workbench_shell

        now = timezone.now()
        order = BuyOrder.objects.create(
            buyer_id='wait_buyer',
            seller_id=self.seller.username,
            total_amount=Decimal('112'),
            dish_items=[{
                'dish_id': 'd1', 'name': '炒饭', 'quantity': 4, 'price': 28,
                'prepared_count': 4, 'served_count': 4,
            }],
            payment_status='pending_payment',
            payment_method='cash',
            order_status='ready_pickup',
            fulfillment_type='delivery',
            estimated_ready_at=now + timedelta(minutes=30),
        )
        DeliveryOrder.objects.create(
            buy_order=order,
            rider_id='r1',
            delivery_fee=Decimal('0'),
            distance_km=Decimal('2.5'),
            pickup_address='店',
            delivery_address='客',
            delivery_status='accepted',
        )
        html = render_to_string('waimai/_shop_work_waiter_panel.html', {
            'orders': [{
                'order': order,
                'phase_label': '已全部送达',
                'dish_groups': build_dual_progress_groups(order.dish_items),
                'serve_label': '交给骑手',
                'delivery_status': '待取餐',
                'rider_id': 'r1',
                'can_mark_all_served': False,
                'can_adjust_wait_time': True,
                'can_dispatch': False,
                'can_reassign': True,
                'can_collect': False,
                'can_confirm_cash': False,
                'can_close_uncollected': False,
                'can_complete_in_store': False,
                'unread_msg_count': 0,
                'log_lines': [],
            }],
            'can_operate': True,
            'workbench_shell': build_workbench_shell(self.seller.username),
            'dispatch_riders': [],
            'form_action': '',
            'shop_work_code': 'tlshop',
            'work_user': self.seller,
        })
        self.assertNotIn('预计', html)

    def test_rider_panel_uses_fold_cards(self):
        """骑手 Tab：大折叠 + 配送单小折叠。"""
        from django.template.loader import render_to_string
        from waimai.workbench_shell_helpers import build_workbench_shell

        html = render_to_string('waimai/_shop_work_rider_panel.html', {
            'active_orders': [],
            'pending_dispatch_orders': [],
            'rider_id': 'rider1',
            'rider_fold_delivery_open': True,
            'rider_fold_cash_open': False,
            'can_operate': True,
            'shop_work_code': 'tlshop',
            'workbench_shell': build_workbench_shell(self.seller.username),
            'form_action': '',
            'show_rider_extras': False,
        })
        self.assertIn('id="rider-delivery"', html)
        self.assertIn('seller-panel-fold', html)
        self.assertIn('📦 配送', html)

    def test_rider_delivery_subfold_renders(self):
        """骑手 Tab：每笔配送为可折叠子卡片。"""
        from django.template.loader import render_to_string
        from waimai.workbench_shell_helpers import build_workbench_shell

        now = timezone.now()
        order = BuyOrder.objects.create(
            buyer_id='sub_buyer',
            seller_id=self.seller.username,
            total_amount=Decimal('30'),
            dish_items=[],
            payment_status='paid',
            order_status='awaiting_delivery',
            fulfillment_type='delivery',
            delivery_address='测试送达地址',
        )
        delivery = DeliveryOrder.objects.create(
            buy_order=order,
            rider_id='rider1',
            delivery_fee=Decimal('2'),
            distance_km=Decimal('1.5'),
            pickup_address='店',
            delivery_address='测试送达地址',
            delivery_status='accepted',
        )
        delivery.handoff_ready = True
        delivery.rider_fold_id = 'delivery-abc12345'
        delivery.rider_fold_title = '配送 #abc12345 · 待取餐 · 测试送达地址'
        html = render_to_string('waimai/_shop_work_rider_panel.html', {
            'active_orders': [delivery],
            'pending_dispatch_orders': [],
            'rider_id': 'rider1',
            'rider_fold_delivery_open': True,
            'rider_fold_cash_open': False,
            'can_operate': True,
            'shop_work_code': 'tlshop',
            'workbench_shell': build_workbench_shell(self.seller.username),
            'form_action': '',
            'show_rider_extras': False,
        })
        self.assertIn('id="delivery-abc12345"', html)
        self.assertIn('data-yc-fold-group="rider-delivery-orders"', html)
        self.assertIn('rider-delivery-subcard', html)
        self.assertIn('我已取餐', html)
