# 本轮流程改进自动验收：货到付款、排序、购物车、买家中心、单设备登录。

from datetime import time, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.template.loader import render_to_string
from django.utils import timezone

from waimai.channel_helpers import channel_session_key
from waimai.dispatch_helpers import (
    maybe_refill_dispatch_after_rider_available,
    query_pending_dispatch_orders,
    try_dispatch_pending_for_rider,
)
from waimai.kitchen_helpers import kitchen_order_can_start, query_kitchen_board_orders
from waimai.models import BuyOrder, DeliveryOrder, Dish, ShopProfile, User
from waimai.operating_helpers import get_operating_settings
from waimai.order_desk_helpers import build_order_desk_context
from waimai.order_helpers import cart_line_key
from waimai.order_workflow_rules import order_can_dispatch
from waimai.payments import (
    buyer_respond_cash_shortfall,
    manager_approve_cash_exception,
    mark_cash_exception,
    rider_collect_cash,
)
from waimai.rider_cash_helpers import (
    create_cash_remittance_request,
    review_cash_remittance_request,
)
from waimai.shop_work_helpers import build_rider_board_context, build_waiter_board_context
from waimai.staff_account_helpers import (
    PERM_DINING_RIDER,
    STAFF_WORK_ON_DUTY,
    set_staff_work_status,
)
from waimai.waiter_helpers import waiter_can_confirm_cash
from waimai.workbench_shell_helpers import build_workbench_shell


class WorkflowImprovementBase(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='flow_seller', password='seller-pass-123', role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='流程试验店',
            shop_code='flowshop',
            address='试验地址',
        )
        self.settings = get_operating_settings(self.seller.username)
        self.settings.business_open = time(0, 0)
        self.settings.business_close = time(23, 59)
        self.settings.save(update_fields=['business_open', 'business_close'])

    def make_order(self, **overrides):
        values = {
            'buyer_id': 'flow_buyer',
            'seller_id': self.seller.username,
            'total_amount': Decimal('20.00'),
            'subtotal_amount': Decimal('20.00'),
            'dish_items': [{'dish_id': 'dish-1', 'name': '试验商品', 'price': 20, 'quantity': 1}],
            'payment_status': 'paid',
            'order_status': 'awaiting_prep',
            'fulfillment_type': 'order',
        }
        values.update(overrides)
        return BuyOrder.objects.create(**values)


class CashDeliveryKitchenTests(WorkflowImprovementBase):
    def test_delivery_cod_is_visible_and_can_start(self):
        order = self.make_order(
            fulfillment_type='delivery',
            payment_method='cash',
            payment_status='pending_payment',
            delivery_address='送达地址',
        )
        visible_ids = set(
            query_kitchen_board_orders(self.seller.username)
            .values_list('order_id', flat=True)
        )
        self.assertIn(order.order_id, visible_ids)
        self.assertTrue(kitchen_order_can_start(order))

    def test_cod_can_dispatch_but_waiter_cannot_confirm_cash(self):
        order = self.make_order(
            fulfillment_type='delivery',
            payment_method='cash',
            payment_status='pending_payment',
            delivery_address='送达地址',
            distance_km=Decimal('2.0'),
        )
        self.assertTrue(order_can_dispatch(order))
        self.assertFalse(waiter_can_confirm_cash(order))
        rows = build_waiter_board_context(
            self.seller.username,
            allow_dispatch=True,
        )['orders']
        target = next(row for row in rows if row['order'].pk == order.pk)
        self.assertTrue(target['can_dispatch'])


class PendingDispatchPoolTests(WorkflowImprovementBase):
    def make_rider(self, username='flow_rider', status=STAFF_WORK_ON_DUTY):
        return User.objects.create_user(
            username=username,
            password='rider-pass-123',
            role='staff',
            employer_seller_id=self.seller.username,
            staff_permissions=[PERM_DINING_RIDER],
            staff_work_status=status,
        )

    def make_cod_delivery(self):
        return self.make_order(
            fulfillment_type='delivery',
            payment_method='cash',
            payment_status='pending_payment',
            delivery_address='待派送达地址',
            distance_km=Decimal('2.0'),
        )

    def test_rider_can_claim_order_from_pending_pool(self):
        rider = self.make_rider()
        order = self.make_cod_delivery()
        self.assertIn(order, list(query_pending_dispatch_orders(self.seller.username)))

        delivery, err = try_dispatch_pending_for_rider(
            self.seller.username,
            rider.username,
            order_id=order.order_id,
        )
        self.assertIsNone(err)
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.rider_id, rider.username)
        self.assertFalse(query_pending_dispatch_orders(self.seller.username).exists())

    def test_rider_on_duty_can_receive_automatic_refill(self):
        rider = self.make_rider(status='off_duty')
        order = self.make_cod_delivery()
        set_staff_work_status(rider, STAFF_WORK_ON_DUTY)

        delivery = DeliveryOrder.objects.get(buy_order=order)
        self.assertEqual(delivery.rider_id, rider.username)

    def test_refill_waits_when_rider_still_has_active_order(self):
        rider = self.make_rider()
        first = self.make_cod_delivery()
        first_delivery, _ = try_dispatch_pending_for_rider(
            self.seller.username,
            rider.username,
            order_id=first.order_id,
        )
        second = self.make_cod_delivery()

        delivery, err = maybe_refill_dispatch_after_rider_available(rider)
        self.assertIsNone(delivery)
        self.assertIsNone(err)
        self.assertTrue(query_pending_dispatch_orders(self.seller.username).filter(pk=second.pk).exists())
        self.assertEqual(first_delivery.rider_id, rider.username)


class CashReconciliationTests(WorkflowImprovementBase):
    def setUp(self):
        super().setUp()
        self.buyer = User.objects.create_user(
            username='flow_buyer', password='buyer-pass-123', role='buyer',
        )
        self.rider = User.objects.create_user(
            username='cash_rider',
            password='rider-pass-123',
            role='staff',
            employer_seller_id=self.seller.username,
            staff_permissions=[PERM_DINING_RIDER],
            staff_work_status=STAFF_WORK_ON_DUTY,
        )

    def make_picked_up_cod(self):
        order = self.make_order(
            fulfillment_type='delivery',
            payment_method='cash',
            payment_status='pending_payment',
            order_status='delivering',
            delivery_address='现金试验地址',
        )
        DeliveryOrder.objects.create(
            buy_order=order,
            rider_id=self.rider.username,
            delivery_fee=Decimal('2.00'),
            distance_km=Decimal('2.0'),
            pickup_address='取餐地址',
            delivery_address='现金试验地址',
            delivery_status='picked_up',
        )
        return order

    def test_shortfall_requires_reason_and_buyer_confirmation(self):
        order = self.make_picked_up_cod()
        ok, _ = rider_collect_cash(order, self.rider.username, '18.00')
        self.assertFalse(ok)

        ok, _ = rider_collect_cash(
            order, self.rider.username, '18.00', '买家现金不足',
        )
        self.assertTrue(ok)
        order.refresh_from_db()
        self.assertEqual(order.cash_shortfall_status, 'buyer_pending')
        self.assertEqual(order.payment_status, 'pending_payment')
        self.assertIsNone(order.cash_collected_at)

        ok, _ = buyer_respond_cash_shortfall(order, self.buyer.username, accept=True)
        self.assertTrue(ok)
        order.refresh_from_db()
        self.assertEqual(order.cash_shortfall_status, 'buyer_confirmed')
        self.assertEqual(order.payment_status, 'paid')
        self.assertIsNotNone(order.cash_collected_at)

    def test_buyer_can_confirm_shortfall_from_order_detail(self):
        order = self.make_picked_up_cod()
        rider_collect_cash(order, self.rider.username, '18.00', '买家现金不足')
        client = Client()
        client.force_login(self.buyer)

        page = client.get(f'/order/{order.order_id}/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '确认实付金额')
        response = client.post(
            f'/order/{order.order_id}/',
            {'cash_shortfall_response': 'accept'},
        )
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.cash_shortfall_status, 'buyer_confirmed')

    def test_rejected_shortfall_needs_manager_fallback(self):
        order = self.make_picked_up_cod()
        rider_collect_cash(order, self.rider.username, '18.00', '买家现金不足')
        buyer_respond_cash_shortfall(order, self.buyer.username, accept=False)
        order.refresh_from_db()

        ok, _ = mark_cash_exception(
            order, self.rider.username, '已电话联系店长，等待处理',
        )
        self.assertTrue(ok)
        order.refresh_from_db()
        self.assertEqual(order.cash_shortfall_status, 'exception')
        self.assertEqual(order.payment_status, 'pending_payment')

        ok, _ = manager_approve_cash_exception(
            order, self.seller.username, '店长电话同意少收并交餐',
        )
        self.assertTrue(ok)
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'completed')
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.delivery_order.delivery_status, 'completed')

    def test_rider_requests_remittance_before_manager_confirms(self):
        order = self.make_picked_up_cod()
        rider_collect_cash(order, self.rider.username, '20.00')
        order.order_status = 'completed'
        order.save(update_fields=['order_status', 'updated_at'])
        DeliveryOrder.objects.filter(buy_order=order).update(
            delivery_status='completed', completed_at=timezone.now(),
        )
        remit, _ = create_cash_remittance_request(
            self.seller.username, self.rider.username, '本班现金',
        )
        self.assertIsNotNone(remit)
        self.assertEqual(remit.total_amount, Decimal('20.00'))
        order.refresh_from_db()
        self.assertIsNone(order.cash_remitted_at)

        ok, _ = review_cash_remittance_request(
            self.seller.username,
            remit.request_id,
            self.seller.username,
            approve=True,
        )
        self.assertTrue(ok)
        order.refresh_from_db()
        remit.refresh_from_db()
        self.assertIsNotNone(order.cash_remitted_at)
        self.assertEqual(remit.status, 'confirmed')

    def test_cash_workbench_panels_render(self):
        exception_order = self.make_picked_up_cod()
        rider_collect_cash(
            exception_order, self.rider.username, '18.00', '买家现金不足',
        )
        buyer_respond_cash_shortfall(exception_order, self.buyer.username, accept=False)
        exception_order.refresh_from_db()
        mark_cash_exception(
            exception_order, self.rider.username, '已电话联系店长，等待处理',
        )

        remit_order = self.make_picked_up_cod()
        rider_collect_cash(remit_order, self.rider.username, '20.00')
        remit_order.order_status = 'completed'
        remit_order.save(update_fields=['order_status', 'updated_at'])
        DeliveryOrder.objects.filter(buy_order=remit_order).update(
            delivery_status='completed', completed_at=timezone.now(),
        )
        create_cash_remittance_request(
            self.seller.username, self.rider.username, '本班现金',
        )

        common = {
            'form_action': '/s/flowshop/work/?view=orders',
            'shop_work_code': 'flowshop',
            'workbench_shell': build_workbench_shell(self.seller.username),
        }
        order_context = build_order_desk_context(
            self.seller.username, work_user=self.seller,
        )
        order_html = render_to_string(
            'waimai/_shop_work_orders_panel.html',
            {**common, **order_context},
        )
        self.assertIn('货到付款异常', order_html)
        self.assertIn('待确认现金交款', order_html)

        rider_context = build_rider_board_context(
            self.rider, self.seller.username,
        )
        rider_html = render_to_string(
            'waimai/_shop_work_rider_panel.html',
            {
                **common,
                **rider_context,
                'can_operate': True,
                'show_rider_extras': False,
            },
        )
        self.assertIn('现金交款', rider_html)
        self.assertIn('电话沟通与管理指示备注', rider_html)


class WorkbenchSortTests(WorkflowImprovementBase):
    def test_order_desk_can_switch_newest_and_oldest(self):
        old_order = self.make_order()
        new_order = self.make_order()
        BuyOrder.objects.filter(pk=old_order.pk).update(
            created_at=timezone.now() - timedelta(hours=1),
        )

        newest = build_order_desk_context(
            self.seller.username, work_user=self.seller, sort_mode='newest',
        )['order_desk_rows']
        oldest = build_order_desk_context(
            self.seller.username, work_user=self.seller, sort_mode='oldest',
        )['order_desk_rows']
        self.assertEqual(newest[0]['order'].pk, new_order.pk)
        self.assertEqual(oldest[0]['order'].pk, old_order.pk)


class AsyncCartTests(WorkflowImprovementBase):
    def test_add_to_cart_returns_replaceable_html_without_redirect(self):
        self.settings.plugin_dining_enabled = False
        self.settings.save(update_fields=['plugin_dining_enabled'])
        dish = Dish.objects.create(
            seller_id=self.seller.username,
            name='无刷新商品',
            price=Decimal('12.00'),
        )
        client = Client()
        session = client.session
        session[channel_session_key(self.seller.username)] = 'order'
        session.save()

        response = client.post(
            f'/shop/?seller_id={self.seller.username}',
            {
                'action': 'add_to_cart',
                'dish_id': str(dish.dish_id),
                'price_tier': 'general',
            },
            HTTP_X_REQUESTED_WITH='YecaoCart',
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['cart_count'], 1)
        self.assertIn('购物车', data['cart_shell_html'])

        line_key = cart_line_key(dish.dish_id, 'general')
        decrease = client.post(
            f'/shop/?seller_id={self.seller.username}',
            {'action': 'decrease_from_cart', 'line_key': line_key},
            HTTP_X_REQUESTED_WITH='YecaoCart',
        )
        self.assertEqual(decrease.status_code, 200)
        self.assertEqual(decrease.json()['cart_count'], 0)

        remove = client.post(
            f'/shop/?seller_id={self.seller.username}',
            {'action': 'remove_from_cart', 'line_key': line_key},
            HTTP_X_REQUESTED_WITH='YecaoCart',
        )
        self.assertEqual(remove.status_code, 200)
        self.assertNotIn('cart-drawer', remove.json()['cart_shell_html'])


class BuyerCenterAndSingleLoginTests(TestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(
            username='center_buyer', password='buyer-pass-123', role='buyer',
        )

    def test_buyer_center_and_password_page_exist(self):
        client = Client()
        response = client.post('/accounts/login/', {
            'username': self.buyer.username,
            'password': 'buyer-pass-123',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.get('/account/').status_code, 200)
        self.assertEqual(client.get('/account/password/').status_code, 200)
        changed = client.post('/account/password/', {
            'old_password': 'buyer-pass-123',
            'new_password1': 'buyer-new-pass-456',
            'new_password2': 'buyer-new-pass-456',
        })
        self.assertEqual(changed.status_code, 302)
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.check_password('buyer-new-pass-456'))
        self.assertEqual(client.get('/account/').status_code, 200)

    def test_new_login_replaces_old_device(self):
        old_device = Client()
        new_device = Client()
        old_device.post('/accounts/login/', {
            'username': self.buyer.username,
            'password': 'buyer-pass-123',
        })
        new_device.post('/accounts/login/', {
            'username': self.buyer.username,
            'password': 'buyer-pass-123',
        })

        old_response = old_device.get('/account/')
        self.assertEqual(old_response.status_code, 302)
        self.assertIn('/accounts/login/', old_response.url)
        self.assertEqual(new_device.get('/account/').status_code, 200)
