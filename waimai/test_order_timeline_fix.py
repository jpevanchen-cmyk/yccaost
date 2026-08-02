# 订单时间线展示规则修复（预计出餐位置、外卖交付节点）

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from waimai.models import BuyOrder, DeliveryOrder, User
from waimai.order_timeline_helpers import (
    TL_DELIVERY_COMPLETED,
    TL_DELIVERY_PICKED_UP,
    TL_GOODS_DELIVERED,
    TL_PAYMENT_RECEIVED,
    TL_PREP_STARTED,
    build_order_timeline,
    record_timeline_event,
)


class OrderTimelineFixTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='tl_seller', password='x', role='seller',
        )

    def _add_event(self, order, code, label, at):
        record_timeline_event(order, event_code=code, label=label, occurred_at=at)

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
        )
        delivery = DeliveryOrder.objects.create(
            buy_order=order,
            delivery_fee=Decimal('3'),
            distance_km=Decimal('1.0'),
            pickup_address='店',
            delivery_address='客',
            delivery_status='completed',
            estimated_delivery_time=base + timedelta(minutes=20),
        )
        self._add_event(order, TL_PREP_STARTED, '开始备货', base)
        self._add_event(order, TL_DELIVERY_PICKED_UP, '骑手已取餐', base + timedelta(minutes=15))
        self._add_event(order, TL_DELIVERY_COMPLETED, '骑手已送达', base + timedelta(minutes=25))
        self._add_event(order, TL_PAYMENT_RECEIVED, '已支付', base + timedelta(minutes=21))

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
        self._add_event(order, TL_GOODS_DELIVERED, '商品已全部交付', now + timedelta(minutes=5))

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
        )
        self._add_event(order, TL_PREP_STARTED, '开始备货', now)

        rows = build_order_timeline(order, viewer='seller')
        labels = [lbl for lbl, _ in rows]
        self.assertIn('预计出餐', labels)
        est_idx = labels.index('预计出餐')
        prep_idx = labels.index('开始备货')
        self.assertGreater(est_idx, prep_idx)
