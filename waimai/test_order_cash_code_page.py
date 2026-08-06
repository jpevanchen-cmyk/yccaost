# 现金支付轻页订单码（方案 A）

from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from waimai.models import BuyOrder, ShopProfile, User
from waimai.order_qr_helpers import order_cash_code_url
from waimai.payments.core import get_payment_settings
from waimai.payments.service import initiate_payment


class OrderCashCodePageTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='occ_seller',
            password='pass12345',
            role='seller',
        )
        self.buyer = User.objects.create_user(
            username='occ_buyer',
            password='pass12345',
            role='buyer',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='轻页码测试店',
            shop_code='occode',
            address='测试地址',
        )
        pay = get_payment_settings(self.seller.username)
        pay.enable_cash = True
        pay.enable_cashier = True
        pay.save(update_fields=['enable_cash', 'enable_cashier'])
        self.order = BuyOrder.objects.create(
            buyer_id=self.buyer.username,
            seller_id=self.seller.username,
            total_amount=Decimal('18.50'),
            subtotal_amount=Decimal('18.50'),
            dish_items=[],
            payment_status='pending_payment',
            payment_method='cash',
            order_status='awaiting_prep',
            fulfillment_type='takeaway',
        )
        self.client = Client()
        self.client.force_login(self.buyer)

    def test_cash_payment_redirects_to_light_page(self):
        order = BuyOrder.objects.create(
            buyer_id=self.buyer.username,
            seller_id=self.seller.username,
            total_amount=Decimal('12.00'),
            subtotal_amount=Decimal('12.00'),
            dish_items=[],
            payment_status='pending_payment',
            order_status='created',
            fulfillment_type='takeaway',
        )
        result = initiate_payment(order, 'cash', '127.0.0.1')
        self.assertTrue(result.ok)
        self.assertEqual(result.redirect_url, order_cash_code_url(order.order_id))

    def test_light_page_renders_usage_and_navigation(self):
        url = reverse('order_cash_code', kwargs={'order_id': self.order.order_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn('您可以出示订单码进行取餐与支付', html)
        self.assertIn('如果需要沟通，请打开订单详情，在订单沟通中进行留言', html)
        self.assertIn('继续点菜', html)
        self.assertIn('查看完整订单', html)
        self.assertIn('订单二维码', html)

    def test_light_page_back_goes_to_shop(self):
        url = reverse('order_cash_code', kwargs={'order_id': self.order.order_id})
        response = self.client.get(url)
        self.assertContains(response, f'/shop/?seller_id={self.seller.username}')

    def test_non_cash_order_redirects_to_detail(self):
        self.order.payment_method = 'wechat_simulate'
        self.order.payment_status = 'paid'
        self.order.payment_time = timezone.now()
        self.order.save(update_fields=['payment_method', 'payment_status', 'payment_time'])
        url = reverse('order_cash_code', kwargs={'order_id': self.order.order_id})
        response = self.client.get(url)
        self.assertRedirects(
            response,
            reverse('order_detail', kwargs={'order_id': self.order.order_id}),
        )
