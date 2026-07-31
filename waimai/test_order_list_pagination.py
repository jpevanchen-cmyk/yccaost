# 卖家订单列表分页测试

from decimal import Decimal

from django.test import TestCase

from waimai.models import BuyOrder, ShopProfile, User
from waimai.order_search_helpers import (
    DEFAULT_ORDER_LIST_PAGE_SIZE,
    build_seller_orders_list_context,
    paginate_seller_orders,
    query_seller_orders_qs,
    resolve_order_list_page_size,
)


class OrderListPaginationTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(username='ord_list_seller', password='x', role='seller')
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='分页测试店',
            shop_code='pg001',
            address='测试',
            is_listed=True,
        )
        for i in range(25):
            BuyOrder.objects.create(
                seller_id=self.seller.username,
                buyer_id=f'buyer{i}',
                total_amount=Decimal('10.00') + Decimal(i),
                order_status='completed',
                payment_status='paid',
                fulfillment_type='takeaway',
                delivery_address='测试地址',
                dish_items='测试菜',
            )

    def test_resolve_order_list_page_size(self):
        self.assertEqual(resolve_order_list_page_size('15'), 15)
        self.assertEqual(resolve_order_list_page_size('99'), DEFAULT_ORDER_LIST_PAGE_SIZE)
        self.assertEqual(resolve_order_list_page_size(None), DEFAULT_ORDER_LIST_PAGE_SIZE)

    def test_paginate_seller_orders_default_page(self):
        qs = query_seller_orders_qs(self.seller.username, {'date_range': 'all'})
        page = paginate_seller_orders(qs, None, 15)
        self.assertEqual(page.number, 1)
        self.assertEqual(len(page.object_list), 15)
        self.assertEqual(page.paginator.count, 25)
        self.assertEqual(page.paginator.num_pages, 2)

    def test_build_seller_orders_list_context_page_two(self):
        ctx = build_seller_orders_list_context(
            self.seller.username,
            {'date_range': 'all', 'page': '2', 'per_page': '10'},
        )
        self.assertEqual(len(ctx['orders']), 10)
        self.assertEqual(ctx['orders_page'].number, 2)
        self.assertEqual(ctx['order_per_page'], 10)
        self.assertIn('per_page=10', ctx['order_list_query'])
        self.assertTrue(hasattr(ctx['orders'][0], 'order_shell'))

    def test_seller_orders_page_renders_compact_row(self):
        self.client.force_login(self.seller)
        resp = self.client.get('/seller-panel/orders/?date_range=all&per_page=10')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'seller-order-row-compact')
        self.assertContains(resp, 'seller-order-compact-grid')
        self.assertContains(resp, 'orders-pagination')
        self.assertContains(resp, '查看订单详情')
        self.assertNotContains(resp, 'seller-order-meta')
