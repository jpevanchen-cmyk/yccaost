# 待派单池展示 · 地址模糊与预计时间

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from waimai.dispatch_display_helpers import (
    blur_address_for_dispatch_preview,
    build_pending_delivery_wait_display,
    build_pending_ready_wait_display,
    enrich_pending_dispatch_order,
    estimate_pending_delivery_deadline,
)
from waimai.models import BuyOrder, ShopProfile, User
from waimai.operating_helpers import get_operating_settings
from waimai.shop_work_helpers import build_rider_board_context
from waimai.staff_account_helpers import PERM_DINING_RIDER, STAFF_WORK_ON_DUTY


class DispatchDisplayTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='dd_seller', password='pass-12345', role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='测试店',
            address='北京市朝阳区建国路88号阳光花园3栋502室',
        )
        self.rider = User.objects.create_user(
            username='dd_rider',
            password='pass-12345',
            role='staff',
            employer_seller_id=self.seller.username,
            staff_permissions=[PERM_DINING_RIDER],
            staff_work_status=STAFF_WORK_ON_DUTY,
        )
        settings = get_operating_settings(self.seller.username)
        settings.delivery_default_wait_minutes = 30
        settings.save(update_fields=['delivery_default_wait_minutes'])

    def test_blur_address_masks_detail_and_default(self):
        self.assertEqual(
            blur_address_for_dispatch_preview('默认地址'),
            '默认地址（详情接单后可见）',
        )
        blurred = blur_address_for_dispatch_preview(
            '海淀区中关村大街1号阳光花园5栋301室 13812345678',
        )
        self.assertIn('花园', blurred)
        self.assertNotIn('13812345678', blurred)
        self.assertNotIn('301', blurred)

    def test_pending_delivery_deadline_from_ready_at(self):
        now = timezone.now()
        order = BuyOrder.objects.create(
            buyer_id='buyer1',
            seller_id=self.seller.username,
            total_amount=Decimal('50'),
            dish_items=[],
            payment_status='paid',
            order_status='ready_pickup',
            fulfillment_type='delivery',
            delivery_address='默认地址',
            estimated_ready_at=now + timedelta(minutes=10),
        )
        deadline = estimate_pending_delivery_deadline(order, now=now)
        self.assertIsNotNone(deadline)
        delta = deadline - order.estimated_ready_at
        self.assertEqual(int(delta.total_seconds()), 30 * 60)

    def test_pending_wait_displays(self):
        now = timezone.now()
        order = BuyOrder.objects.create(
            buyer_id='buyer2',
            seller_id=self.seller.username,
            total_amount=Decimal('30'),
            dish_items=[],
            payment_status='paid',
            order_status='ready_pickup',
            fulfillment_type='delivery',
            delivery_address='朝阳区xx路10号',
            estimated_ready_at=now + timedelta(minutes=12),
        )
        enrich_pending_dispatch_order(order, shop_address='朝阳区建国路88号')
        self.assertIn('建国路', order.pending_pickup_address or '')
        self.assertNotIn('88', order.pending_pickup_address.replace('***', ''))
        self.assertEqual(order.pending_pickup_wait['label'], '预计可取餐')
        self.assertEqual(order.pending_delivery_wait['label'], '预计送达（预估）')

    def test_rider_board_enriches_pending_pool(self):
        now = timezone.now()
        BuyOrder.objects.create(
            buyer_id='buyer3',
            seller_id=self.seller.username,
            total_amount=Decimal('40'),
            dish_items=[{'name': '菜', 'quantity': 1, 'price': 40.0, 'prepared_count': 1, 'served_count': 1}],
            payment_status='paid',
            order_status='ready_pickup',
            fulfillment_type='delivery',
            delivery_address='默认地址',
            estimated_ready_at=now + timedelta(minutes=5),
        )
        ctx = build_rider_board_context(self.rider, self.seller.username)
        self.assertEqual(len(ctx['pending_dispatch_orders']), 1)
        pending = ctx['pending_dispatch_orders'][0]
        self.assertEqual(pending.pending_delivery_address, '默认地址（详情接单后可见）')
        self.assertIsNotNone(pending.pending_pickup_wait)
