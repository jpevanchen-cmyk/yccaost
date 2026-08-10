# 进度 83：取消方案 B、历程、店主工牌、通知、骑手按钮

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import Client, RequestFactory, TestCase
from django.template.loader import render_to_string
from django.utils import timezone
from .time_helpers import now_local_wall

from waimai.flash_notice_helpers import collect_page_notices
from waimai.models import BuyOrder, DeliveryOrder, ShopProfile
from waimai.order_cancel_helpers import cancel_order_by_buyer
from waimai.order_timeline_helpers import build_order_timeline
from waimai.order_status_transition_helpers import buyer_can_self_cancel_order
from waimai.staff_account_helpers import (
    authenticate_shop_work_user,
    create_owner_workbench_staff,
    staff_display_username,
    staff_internal_username,
)
from waimai.workbench_shell_helpers import build_workbench_shell

User = get_user_model()


class Progress83Base(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='shop83',
            password='pass1234',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='测试店83',
            shop_type='restaurant',
            address='测试路1号',
            shop_code='shop83',
            is_listed=True,
        )
        self.buyer = User.objects.create_user(
            username='buyer83',
            password='pass1234',
            role='buyer',
        )


class BuyerCancelCreatedTests(Progress83Base):
    def test_created_order_buyer_can_self_cancel(self):
        order = BuyOrder.objects.create(
            buyer_id=self.buyer.username,
            seller_id=self.seller.username,
            total_amount=Decimal('20.00'),
            dish_items=[],
            payment_status='pending_payment',
            order_status='created',
            fulfillment_type='order',
        )
        self.assertTrue(buyer_can_self_cancel_order(order))
        ok, _ = cancel_order_by_buyer(order, self.buyer)
        self.assertTrue(ok)
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'cancelled')


class OrderTimelineTests(Progress83Base):
    def test_build_timeline_shows_order_created_from_source(self):
        order = BuyOrder.objects.create(
            buyer_id=self.buyer.username,
            seller_id=self.seller.username,
            total_amount=Decimal('10.00'),
            dish_items=[],
            payment_status='pending_payment',
            order_status='created',
            fulfillment_type='order',
        )
        rows = build_order_timeline(order, viewer='buyer')
        labels = [label for label, _ in rows]
        self.assertIn('订单已生成', labels)


class OwnerWorkbenchStaffTests(Progress83Base):
    def test_create_owner_workbench_staff_uses_seller_login_name(self):
        staff = create_owner_workbench_staff(self.seller, 'pass1234')
        self.assertIsNotNone(staff)
        self.assertEqual(staff.username, staff_internal_username('shop83', 'shop83'))
        self.assertEqual(staff_display_username(staff.username), 'shop83')
        self.assertTrue(staff.staff_permissions)

    def test_seller_cannot_login_workbench_directly(self):
        factory = RequestFactory()
        request = factory.post('/')
        request.session = {}
        user = authenticate_shop_work_user(
            request, 'shop83', 'shop83', 'pass1234',
        )
        self.assertIsNone(user)

    def test_owner_badge_can_login_workbench(self):
        create_owner_workbench_staff(self.seller, 'pass1234')
        factory = RequestFactory()
        request = factory.post('/')
        request.session = {}
        user = authenticate_shop_work_user(
            request, 'shop83', 'shop83', 'pass1234',
        )
        self.assertIsNotNone(user)
        self.assertEqual(user.role, 'staff')


class FlashNoticeTests(TestCase):
    def test_collect_page_notices_consumes_messages_once(self):
        client = Client()
        session = client.session
        session.save()
        request = RequestFactory().get('/')
        request.session = client.session
        setattr(request, '_messages', FallbackStorage(request))
        from django.contrib import messages

        messages.success(request, '操作成功')
        first = collect_page_notices(request)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]['text'], '操作成功')
        request.session.save()
        second = collect_page_notices(request)
        self.assertEqual(second, [])


class WorkbenchNoticeAlign83Tests(TestCase):
    """工作台面板不再内嵌 Django messages 绿色长条，改由 yc_notice 弹窗。"""

    def test_waiter_panel_no_inline_flash_messages(self):
        from django.template.loader import render_to_string
        from django.contrib.messages.storage.fallback import FallbackStorage

        from waimai.workbench_shell_helpers import build_workbench_shell

        request = RequestFactory().get('/')
        request.session = {}
        setattr(request, '_messages', FallbackStorage(request))
        from django.contrib import messages

        messages.success(request, '已一键备好 3 份商品')
        html = render_to_string('waimai/_shop_work_waiter_panel.html', {
            'messages': messages.get_messages(request),
            'orders': [],
            'can_operate': True,
            'form_action': '/work/',
            'shop_work_code': 'test',
            'workbench_shell': build_workbench_shell('test_seller'),
        })
        self.assertNotIn('已一键备好 3 份商品', html)

    def test_kitchen_panel_no_inline_flash_messages(self):
        from django.template.loader import render_to_string
        from django.contrib.messages.storage.fallback import FallbackStorage

        from waimai.workbench_shell_helpers import build_workbench_shell

        request = RequestFactory().get('/')
        request.session = {}
        setattr(request, '_messages', FallbackStorage(request))
        from django.contrib import messages

        messages.success(request, '后厨已开始备货')
        html = render_to_string('waimai/_shop_work_kitchen_panel.html', {
            'messages': messages.get_messages(request),
            'orders': [],
            'summary_rows': [],
            'can_operate': True,
            'form_action': '/work/',
            'shop_work_code': 'test',
            'workbench_shell': build_workbench_shell('test_seller'),
        })
        self.assertNotIn('后厨已开始备货', html)


class RiderStartedButtonTests(Progress83Base):
    def test_in_transit_shows_started_delivery_button(self):
        order = BuyOrder.objects.create(
            buyer_id=self.buyer.username,
            seller_id=self.seller.username,
            total_amount=Decimal('30.00'),
            dish_items=[],
            payment_status='paid',
            order_status='delivering',
            fulfillment_type='delivery',
            delivery_address='顾客地址',
        )
        delivery = DeliveryOrder.objects.create(
            buy_order=order,
            rider_id='rider1',
            delivery_fee=Decimal('3.00'),
            distance_km=Decimal('1.0'),
            pickup_address='店址',
            delivery_address='顾客地址',
            delivery_status='in_transit',
            in_transit_at=now_local_wall(),
        )
        delivery.handoff_ready = True
        delivery.rider_fold_id = 'delivery-test1234'
        delivery.rider_fold_title = '配送 #test1234 · 配送中 · 顾客地址'
        html = render_to_string(
            'waimai/_shop_work_rider_panel.html',
            {
                'active_orders': [delivery],
                'can_operate': True,
                'rider_id': 'rider1',
                'shop_work_code': 'shop83',
                'workbench_shell': build_workbench_shell(self.seller.username),
                'pending_dispatch_orders': [],
                'rider_fold_delivery_open': True,
                'rider_fold_cash_open': False,
                'form_action': '',
                'show_rider_extras': False,
            },
        )
        self.assertIn('已开始送餐', html)
        self.assertNotRegex(html, r'type="submit"[^>]*>\s*开始送餐')
