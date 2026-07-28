# H4 新手体验引导（幻灯片式小步演示）



from decimal import Decimal



from django.test import TestCase



from waimai.experience_helpers import mark_shop_official

from waimai.models import Dish, ShopProfile, User

from waimai.onboarding_helpers import (

    OFFICIAL_SHOP_NAME,

    build_onboarding_boot_payload,

    get_official_shop_profile,

)

from waimai.plugin_runtime.registry import set_plugin_enabled





class OnboardingHelpersTests(TestCase):

    def setUp(self):

        self.seller = User.objects.create_user(

            username='ob_seller',

            password='x',

            role='seller',

        )

        self.shop = ShopProfile.objects.create(

            seller_id=self.seller.username,

            shop_name=OFFICIAL_SHOP_NAME,

            shop_code='obdemo',

            address='演示地址',

            is_listed=True,

        )

        mark_shop_official(self.seller.username)



    def test_get_official_shop(self):

        found = get_official_shop_profile()

        self.assertIsNotNone(found)

        self.assertEqual(found.shop_name, OFFICIAL_SHOP_NAME)



    def test_boot_payload_seller_majors_structure(self):

        boot = build_onboarding_boot_payload()

        self.assertTrue(boot['enabled'])

        seller = boot['tracks']['seller']

        self.assertEqual(seller[0]['id'], 'seller-1')

        self.assertEqual(seller[2]['id'], 'seller-3')

        self.assertEqual(seller[3]['id'], 'seller-4a')

        self.assertEqual(seller[4]['id'], 'seller-4b')

        self.assertGreaterEqual(len(seller[0]['microSteps']), 8)

        self.assertIn('productShell', boot)

    def test_boot_auto_advance_seconds(self):
        boot = build_onboarding_boot_payload()
        self.assertEqual(boot['autoAdvanceSeconds'], 8)
        self.assertEqual(boot['autoAdvanceSecondsTypeDemo'], 12)
        seller = boot['tracks']['seller']
        typed = None
        plain = None
        for major in seller:
            for step in major['microSteps']:
                if step.get('demoType') == 'type' and typed is None:
                    typed = step
                if not step.get('demoType') and plain is None:
                    plain = step
                if typed and plain:
                    break
            if typed and plain:
                break
        if plain:
            self.assertEqual(plain.get('autoSeconds'), 8)
        if typed:
            self.assertEqual(typed.get('autoSeconds'), 12)



    def test_boot_with_plugins_adds_optional_majors(self):

        set_plugin_enabled('dining', self.seller.username, True)

        set_plugin_enabled('fulfillment', self.seller.username, True)

        boot = build_onboarding_boot_payload()

        ids = [m['id'] for m in boot['tracks']['seller']]

        self.assertIn('seller-8', ids)

        self.assertIn('seller-9', ids)

        self.assertTrue(boot['diningEnabled'])



    def test_seller1_first_micro_highlights_nav(self):

        boot = build_onboarding_boot_payload()

        first = boot['tracks']['seller'][0]['microSteps'][0]

        self.assertEqual(first['page'], 'home')

        self.assertIn('nav-shop-register', first['selector'])





class OnboardingViewTests(TestCase):

    def setUp(self):

        self.seller = User.objects.create_user(

            username='ob_view_seller',

            password='x',

            role='seller',

        )

        self.shop = ShopProfile.objects.create(

            seller_id=self.seller.username,

            shop_name=OFFICIAL_SHOP_NAME,

            shop_code='obdemo',

            address='演示地址',

            is_listed=True,

        )

        mark_shop_official(self.seller.username)

        Dish.objects.create(

            seller_id=self.seller.username,

            name='演示菜',

            price=Decimal('8.88'),

            is_active=True,

        )



    def test_preview_seller_products_ok(self):

        resp = self.client.get('/onboarding/preview/seller/products/')

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, 'sales-ranking')



    def test_preview_seller_homepage_ok(self):

        resp = self.client.get('/onboarding/preview/seller/homepage/')

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, 'home-page-settings')



    def test_preview_print_qr_ok(self):

        resp = self.client.get('/onboarding/preview/seller/print-qr/')

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, 'G1-8')



    def test_preview_work_login_ok(self):

        resp = self.client.get('/onboarding/preview/work/login/')

        self.assertEqual(resp.status_code, 200)



    def test_preview_dine_redirect_without_plugin(self):
        shop = get_official_shop_profile()
        set_plugin_enabled('dining', shop.seller_id, False)
        resp = self.client.get('/onboarding/preview/seller/dine/')
        self.assertEqual(resp.status_code, 302)

    def test_preview_dine_ok_with_plugin(self):
        shop = get_official_shop_profile()
        set_plugin_enabled('dining', shop.seller_id, True)

        resp = self.client.get('/onboarding/preview/seller/dine/')

        self.assertEqual(resp.status_code, 200)



    def test_home_has_onboarding_zone(self):

        resp = self.client.get('/')

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, 'onboarding-step-picker-modal')



    def test_preview_without_official_shop_redirects(self):

        ShopProfile.objects.filter(seller_id=self.seller.username).update(is_official=False)

        resp = self.client.get('/onboarding/preview/seller/products/')

        self.assertEqual(resp.status_code, 302)

    def test_preview_seller_orders_and_detail_ok(self):
        from waimai.models import BuyOrder

        resp = self.client.get('/onboarding/preview/seller/orders/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'orders-intro')
        order = BuyOrder.objects.filter(seller_id=self.seller.username).first()
        if not order:
            order = BuyOrder.objects.create(
                seller_id=self.seller.username,
                buyer_id='demo_buyer',
                total_amount=Decimal('12.00'),
                order_status='pending',
                payment_status='pending_payment',
                dish_items=[{'name': '演示菜', 'price': 8.88, 'quantity': 1}],
            )
        resp = self.client.get(f'/onboarding/preview/seller/orders/{order.order_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'order-detail-hero')

    def test_preview_work_hub_rider_ok(self):
        resp = self.client.get('/onboarding/preview/work/rider/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'work-rider-remit')

    def test_preview_delivery_ok_with_plugin(self):
        from waimai.onboarding_helpers import get_official_shop_profile
        from waimai.plugin_runtime.registry import set_plugin_enabled

        shop = get_official_shop_profile()
        set_plugin_enabled('fulfillment', shop.seller_id, True)
        resp = self.client.get('/onboarding/preview/seller/delivery/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'delivery-intro')


