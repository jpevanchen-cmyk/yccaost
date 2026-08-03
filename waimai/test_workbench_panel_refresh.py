# 进度 80-2b/2c：店铺工作台 Panel（后厨 / 服务员 / 订单台 / 收银 / 骑手）

import json
from datetime import time
from decimal import Decimal

from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from waimai.kitchen_handlers import handle_kitchen_board_post
from waimai.models import BuyOrder, DeliveryOrder, ShopProfile, User
from waimai.operating_helpers import get_operating_settings
from waimai.order_desk_handlers import handle_order_desk_post
from waimai.panel_refresh_helpers import PANEL_REQUEST_HEADER
from waimai.workbench_panel_helpers import attach_shop_work_panel_ctx


def _attach_session(request):
    middleware = SessionMiddleware(lambda req: None)
    middleware.process_request(request)
    request.session.save()
    setattr(request, '_messages', FallbackStorage(request))


def _dish_items_for_kitchen():
    return [{
        'line_id': 'line-1',
        'dish_id': 'dish-k1',
        'name': '试验菜',
        'price': 10,
        'quantity': 2,
        'prepared_count': 0,
        'served_count': 0,
    }]


class WorkbenchPanelKitchenTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='wb_kitchen_seller',
            password='pass12345',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='Panel 后厨店',
            shop_code='wbkit',
            address='试验地址',
        )
        settings = get_operating_settings(self.seller.username)
        settings.business_open = time(0, 0)
        settings.business_close = time(23, 59)
        settings.save(update_fields=['business_open', 'business_close'])
        self.order = BuyOrder.objects.create(
            buyer_id='buyer1',
            seller_id=self.seller.username,
            total_amount=Decimal('20.00'),
            dish_items=_dish_items_for_kitchen(),
            payment_status='paid',
            payment_method='wechat_simulate',
            order_status='preparing',
            fulfillment_type='takeaway',
        )
        self.factory = RequestFactory()

    def _panel_ctx(self, request, *, view='kitchen'):
        attach_shop_work_panel_ctx(
            request,
            seller_id=self.seller.username,
            shop_code='wbkit',
            view=view,
            work_user=self.seller,
            sort_mode='newest',
            form_action='/s/wbkit/work/?view=kitchen&sort=newest',
            redirect_to='/s/wbkit/work/?view=kitchen',
            can_operate_kitchen=True,
            can_operate_waiter=True,
        )

    def test_kitchen_mark_prepared_returns_panel_json(self):
        request = self.factory.post('/', {
            'mark_prepared_unit': '1',
            'order_id': str(self.order.order_id),
            'dish_id': 'dish-k1',
        }, HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER)
        request.user = self.seller
        request.shop_work_user = self.seller
        _attach_session(request)
        self._panel_ctx(request)
        response = handle_kitchen_board_post(
            request, self.seller.username, redirect_to='/s/wbkit/work/?view=kitchen',
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['ok'])
        self.assertEqual(data['panel_id'], 'work-kitchen-panel-body')
        self.assertIn('试验菜', data['html'])

    def test_kitchen_start_preparing_returns_panel_json(self):
        pending = BuyOrder.objects.create(
            buyer_id='buyer2',
            seller_id=self.seller.username,
            total_amount=Decimal('15.00'),
            dish_items=_dish_items_for_kitchen(),
            payment_status='paid',
            payment_method='wechat_simulate',
            order_status='awaiting_prep',
            fulfillment_type='takeaway',
        )
        request = self.factory.post('/', {
            'start_preparing': '1',
            'order_id': str(pending.order_id),
        }, HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER)
        request.user = self.seller
        request.shop_work_user = self.seller
        _attach_session(request)
        self._panel_ctx(request)
        response = handle_kitchen_board_post(
            request, self.seller.username, redirect_to='/s/wbkit/work/?view=kitchen',
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['ok'])
        self.assertIn('后厨已开始备货', data.get('message', ''))
        pending.refresh_from_db()
        self.assertEqual(pending.order_status, 'preparing')


class WorkbenchPanelOrderDeskTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='wb_orders_seller',
            password='pass12345',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='Panel 订单台店',
            shop_code='wbo',
            address='试验地址',
        )
        self.order = BuyOrder.objects.create(
            buyer_id='buyer1',
            seller_id=self.seller.username,
            total_amount=Decimal('10.00'),
            dish_items=[{
                'line_id': 'line-1',
                'dish_id': 'dish-o1',
                'name': '基础商品',
                'price': 10,
                'quantity': 1,
                'prepared_count': 0,
                'served_count': 0,
            }],
            payment_status='paid',
            payment_method='wechat_simulate',
            order_status='preparing',
            fulfillment_type='order',
        )
        self.factory = RequestFactory()

    def test_order_desk_mark_processed_panel_json(self):
        request = self.factory.post('/', {
            'order_desk_mark_processed': '1',
            'order_id': str(self.order.order_id),
            'dish_id': 'dish-o1',
        }, HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER)
        request.user = self.seller
        request.shop_work_user = self.seller
        _attach_session(request)
        attach_shop_work_panel_ctx(
            request,
            seller_id=self.seller.username,
            shop_code='wbo',
            view='orders',
            work_user=self.seller,
            sort_mode='newest',
            form_action='/s/wbo/work/?view=orders&sort=newest',
            redirect_to='/s/wbo/work/?view=orders',
        )
        response = handle_order_desk_post(
            request,
            self.seller.username,
            redirect_to='/s/wbo/work/?view=orders',
            work_user=self.seller,
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['ok'])
        self.assertEqual(data['panel_id'], 'work-orders-panel-body')

    def test_order_desk_without_panel_still_redirects(self):
        client = Client()
        client.force_login(self.seller)
        from waimai.shop_work_auth import establish_shop_work_session

        session = client.session
        establish_shop_work_session(
            type('R', (), {'session': session})(),
            self.seller,
            seller_id=self.seller.username,
            shop_code='wbo',
        )
        session.save()
        url = reverse('shop_work', kwargs={'shop_code': 'wbo'}) + '?view=orders'
        response = client.post(url, {
            'order_desk_mark_processed': '1',
            'order_id': str(self.order.order_id),
            'dish_id': 'dish-o1',
        })
        self.assertEqual(response.status_code, 302)


class WorkbenchPanelCashierTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='wb_cash_seller',
            password='pass12345',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='Panel 收银店',
            shop_code='wbcash',
            address='试验地址',
        )
        from waimai.payments.core import get_payment_settings

        pay = get_payment_settings(self.seller.username)
        pay.enable_cashier = True
        pay.enable_cash = True
        pay.save()
        self.order = BuyOrder.objects.create(
            buyer_id='buyer1',
            seller_id=self.seller.username,
            total_amount=Decimal('25.00'),
            subtotal_amount=Decimal('25.00'),
            dish_items=[],
            payment_status='pending_payment',
            order_status='awaiting_payment',
            fulfillment_type='order',
        )
        self.factory = RequestFactory()

    def test_cashier_collect_returns_panel_json(self):
        request = self.factory.post('/', {
            'cashier_action': 'collect',
            'order_id': str(self.order.order_id),
            'pay_mode': 'cash',
            'collected_amount': '25.00',
        }, HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER)
        request.user = self.seller
        request.shop_work_user = self.seller
        _attach_session(request)
        attach_shop_work_panel_ctx(
            request,
            seller_id=self.seller.username,
            shop_code='wbcash',
            view='cashier',
            work_user=self.seller,
            sort_mode='newest',
            form_action='/s/wbcash/work/?view=cashier&sort=newest',
            redirect_to='/s/wbcash/work/?view=cashier',
            can_operate_cashier=True,
        )
        from waimai.cashier_handlers import handle_cashier_post

        response = handle_cashier_post(
            request,
            self.seller.username,
            'wbcash',
            redirect_to='/s/wbcash/work/?view=cashier',
            work_user=self.seller,
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['ok'])
        self.assertEqual(data['panel_id'], 'work-cashier-panel-body')
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'paid')


class WorkbenchPanelRiderTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='wb_rider_seller',
            password='pass12345',
            role='seller',
        )
        from waimai.staff_account_helpers import PERM_DINING_RIDER, STAFF_WORK_ON_DUTY

        self.rider = User.objects.create_user(
            username='wb_rider_user',
            password='pass12345',
            role='staff',
            employer_seller_id=self.seller.username,
            staff_permissions=[PERM_DINING_RIDER],
            staff_work_status=STAFF_WORK_ON_DUTY,
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='Panel 骑手店',
            shop_code='wbrider',
            address='试验地址',
        )
        buy_order = BuyOrder.objects.create(
            buyer_id='buyer1',
            seller_id=self.seller.username,
            total_amount=Decimal('20.00'),
            dish_items=[{
                'name': '测试菜', 'quantity': 1, 'price': 20.0,
                'served_count': 1, 'prepared_count': 1,
            }],
            payment_status='paid',
            order_status='awaiting_delivery',
            fulfillment_type='delivery',
            delivery_address='测试地址',
        )
        self.delivery = DeliveryOrder.objects.create(
            buy_order=buy_order,
            rider_id=self.rider.username,
            delivery_fee=Decimal('2.00'),
            distance_km=Decimal('1.0'),
            pickup_address='店里',
            delivery_address='测试地址',
            delivery_status='picked_up',
        )
        self.factory = RequestFactory()

    def test_rider_start_delivery_returns_panel_json(self):
        request = self.factory.post('/', {
            'action': 'start_delivery',
            'delivery_id': str(self.delivery.delivery_id),
        }, HTTP_X_REQUESTED_WITH=PANEL_REQUEST_HEADER)
        request.user = self.rider
        request.shop_work_user = self.rider
        _attach_session(request)
        attach_shop_work_panel_ctx(
            request,
            seller_id=self.seller.username,
            shop_code='wbrider',
            view='rider',
            work_user=self.rider,
            sort_mode='newest',
            form_action='/s/wbrider/work/?view=rider&sort=newest',
            redirect_to='/s/wbrider/work/?view=rider',
            can_operate_rider=True,
            show_rider_extras=True,
        )
        from waimai.workbench_handlers import handle_my_deliveries_post

        response = handle_my_deliveries_post(
            request,
            seller_id=self.seller.username,
            shop_code='wbrider',
            user=self.rider,
            redirect_to='/s/wbrider/work/?view=rider',
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['ok'])
        self.assertEqual(data['panel_id'], 'work-rider-panel-body')
        self.assertIn('scroll_to', data)
        self.assertTrue(str(data['scroll_to']).startswith('delivery-'))
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.delivery_status, 'in_transit')
