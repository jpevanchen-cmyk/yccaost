# 新版新手体验（独立模块 v2）测试



from decimal import Decimal



from django.test import TestCase



from waimai.experience_helpers import mark_shop_official

from waimai.menu_helpers import get_active_menu_profile, populate_profile_with_dishes

from waimai.models import Dish, MenuProfile, ShopProfile, User

from waimai.onboarding.boot import build_experience_boot_payload

from waimai.onboarding.demo_cleanup import DEMO_DISH_NAME, DEMO_MENU_PROFILE_NAME, cleanup_experience_demo_data

from waimai.onboarding.official_shop import OFFICIAL_SHOP_NAME





class ExperienceBootTests(TestCase):

    def setUp(self):

        self.seller = User.objects.create_user(

            username='exp_seller',

            password='x',

            role='seller',

        )

        self.shop = ShopProfile.objects.create(

            seller_id=self.seller.username,

            shop_name=OFFICIAL_SHOP_NAME,

            shop_code='expdemo',

            address='演示地址',

            is_listed=True,

        )

        mark_shop_official(self.seller.username)

        Dish.objects.create(

            seller_id=self.seller.username,

            name='演示可乐',

            price=Decimal('3.50'),

            is_active=True,

        )

        profile = MenuProfile.objects.create(seller_id=self.seller.username, name='通用清单')

        populate_profile_with_dishes(profile, self.seller.username)

        from waimai.operating_helpers import get_operating_settings

        settings = get_operating_settings(self.seller.username)

        settings.active_menu_profile = profile

        settings.plugin_dining_enabled = True

        settings.save(update_fields=['active_menu_profile', 'plugin_dining_enabled'])



    def test_boot_has_eight_majors_when_dining(self):

        from waimai.operating_helpers import get_operating_settings

        settings = get_operating_settings(self.seller.username)

        settings.plugin_fulfillment_enabled = False

        settings.save(update_fields=['plugin_fulfillment_enabled'])

        boot = build_experience_boot_payload()

        self.assertTrue(boot['enabled'])

        self.assertEqual(boot['version'], 2)

        seller = boot['tracks']['seller']

        self.assertEqual(len(seller), 11)

        self.assertEqual(seller[0]['id'], 'seller-1')

        self.assertEqual(seller[7]['id'], 'seller-8')

        self.assertEqual(seller[8]['id'], 'seller-11')

        self.assertEqual(seller[9]['id'], 'seller-12')

        self.assertEqual(seller[10]['id'], 'seller-13')

        self.assertTrue(seller[2].get('cleanupOnComplete'))

        self.assertTrue(seller[5].get('cleanupOnComplete'))

        self.assertTrue(seller[7].get('cleanupOnComplete'))

        orders_major = seller[9]

        self.assertEqual(orders_major['id'], 'seller-12')

        self.assertEqual(len(orders_major['microSteps']), 24)

        self.assertEqual(orders_major['microSteps'][1]['foldLayout'], ['boss-order-notify'])

        self.assertEqual(orders_major['microSteps'][14]['selector'], '[data-yc-tour="preview-banner"]')

        self.assertIn('/experience/preview/seller/orders/', boot['pages']['preview_orders'])

        homepage_major = seller[10]

        self.assertEqual(homepage_major['id'], 'seller-13')

        self.assertEqual(len(homepage_major['microSteps']), 27)

        self.assertIn('/experience/preview/seller/homepage/', boot['pages']['preview_homepage'])



    def test_boot_has_nine_majors_when_dining_and_fulfillment(self):

        from waimai.operating_helpers import get_operating_settings

        settings = get_operating_settings(self.seller.username)

        settings.plugin_fulfillment_enabled = True

        settings.save(update_fields=['plugin_fulfillment_enabled'])

        boot = build_experience_boot_payload()

        seller = boot['tracks']['seller']

        self.assertEqual(len(seller), 12)

        self.assertEqual(seller[7]['id'], 'seller-8')

        self.assertEqual(seller[8]['id'], 'seller-10')

        self.assertEqual(seller[9]['id'], 'seller-11')

        self.assertEqual(seller[10]['id'], 'seller-12')

        self.assertEqual(seller[11]['id'], 'seller-13')

        delivery_major = seller[8]

        self.assertEqual(len(delivery_major['microSteps']), 12)

        self.assertEqual(delivery_major['microSteps'][0]['selector'], '[data-yc-tour="nav-delivery"]')

        self.assertEqual(delivery_major['microSteps'][-1]['title'], '配送费规则体验结束')

        self.assertIn('/experience/preview/seller/delivery/', boot['pages']['preview_delivery'])

        self.assertNotIn('preview_delivery', boot['writablePages'])

        payment_major = seller[9]

        self.assertEqual(payment_major['microSteps'][0]['selector'], '[data-yc-tour="nav-payment"]')

        self.assertEqual(payment_major['microSteps'][-1]['title'], '支付设置体验结束')

        self.assertIn('订单管理', payment_major['microSteps'][-1]['body'])

        self.assertIn('/experience/preview/seller/payment/', boot['pages']['preview_payment'])

        self.assertNotIn('preview_payment', boot['writablePages'])

        orders_major = seller[10]

        self.assertEqual(orders_major['microSteps'][0]['selector'], '[data-yc-tour="nav-orders"]')

        self.assertEqual(orders_major['microSteps'][-1]['title'], '订单管理体验结束')

        self.assertIn('/experience/preview/seller/orders/', boot['pages']['preview_orders'])

        homepage_major = seller[11]

        self.assertEqual(homepage_major['id'], 'seller-13')

        self.assertIn('/experience/preview/seller/homepage-showcase/', boot['pages']['preview_homepage_showcase'])



    def test_boot_has_menu_tour_meta(self):

        boot = build_experience_boot_payload()

        self.assertEqual(boot['urlFlag'], 'exp')

        self.assertIn('/experience/preview/seller/products/', boot['pages']['preview_products'])

        self.assertTrue(boot['demoCopyProfileId'])

        self.assertIn('/experience/cleanup/', boot['cleanupUrl'])

        self.assertIn('preview_products', boot['writablePages'])

        self.assertIn('/experience/preview/seller/print-qr/', boot['pages']['preview_print_qr'])

        self.assertIn('/experience/preview/seller/workbench/', boot['pages']['preview_workbench_manage'])

        self.assertIn('/experience/preview/seller/dine/', boot['pages']['preview_dine'])

        self.assertIn('preview_dine', boot['writablePages'])

        dine_major = boot['tracks']['seller'][7]

        self.assertEqual(dine_major['id'], 'seller-8')

        self.assertGreaterEqual(len(dine_major['microSteps']), 30)

        self.assertEqual(dine_major['microSteps'][-1]['title'], '堂食营业体验结束')

        workbench_major = boot['tracks']['seller'][6]
        self.assertEqual(workbench_major['id'], 'seller-7')
        # 合并 3 个小步后共 38 步；有履约插件时 +2
        self.assertIn(len(workbench_major['microSteps']), (38, 40))
        self.assertEqual(workbench_major['microSteps'][-1]['title'], '本大步结束')
        self.assertEqual(workbench_major['microSteps'][-1]['selector'], '[data-yc-tour="fold-staff-list"]')
        self.assertEqual(workbench_major['microSteps'][0]['foldLayout'], [])
        self.assertEqual(workbench_major['microSteps'][1]['foldLayout'], ['workbench-qr'])
        self.assertEqual(workbench_major['microSteps'][-1]['foldLayout'], ['staff-account-list'])
        self.assertEqual(workbench_major['microSteps'][1].get('openFold'), '')

        operating_major = boot['tracks']['seller'][1]
        self.assertEqual(operating_major['id'], 'seller-2')
        self.assertEqual(operating_major['microSteps'][0]['foldLayout'], [])
        self.assertEqual(operating_major['microSteps'][1]['foldLayout'], ['status-form'])

        menu_major = boot['tracks']['seller'][2]
        self.assertEqual(menu_major['microSteps'][0]['foldLayout'], ['sales-ranking'])
        self.assertEqual(menu_major['microSteps'][5]['foldLayout'], ['menu-panel'])

        add_major = boot['tracks']['seller'][4]
        self.assertEqual(add_major['microSteps'][0]['foldLayout'], ['product-add'])
        self.assertEqual(add_major['microSteps'][-1]['foldLayout'], [])

        edit_major = boot['tracks']['seller'][5]
        self.assertEqual(edit_major['microSteps'][0]['foldLayout'], [])

        register_major = boot['tracks']['seller'][0]
        self.assertEqual(len(register_major['microSteps']), 9)
        self.assertEqual(
            register_major['microSteps'][1]['selector'],
            '[data-yc-tour="shop-register-title"]',
        )
        self.assertIn('skipHintSeenKey', boot)

        menu_major = boot['tracks']['seller'][2]

        self.assertEqual(len(menu_major['microSteps']), 25)

        self.assertTrue(menu_major.get('cleanupOnComplete'))

        self.assertEqual(len(boot['tracks']['seller'][3]['microSteps']), 4)

        self.assertEqual(len(boot['tracks']['seller'][4]['microSteps']), 12)

        add_major = boot['tracks']['seller'][4]
        self.assertEqual(
            add_major['microSteps'][11]['selector'],
            '[data-yc-tour="demo-s5-step12-shot"]',
        )

        self.assertEqual(len(boot['tracks']['seller'][5]['microSteps']), 6)

        edit_major = boot['tracks']['seller'][5]
        self.assertEqual(
            edit_major['microSteps'][0]['selector'],
            '[data-yc-tour="demo-s6-shot-1"]',
        )
        self.assertEqual(edit_major['microSteps'][5]['page'], 'preview_products')
        self.assertNotEqual(edit_major['microSteps'][0].get('demoType'), 'action')





class ExperienceViewTests(TestCase):

    def setUp(self):

        self.seller = User.objects.create_user(

            username='exp_view_seller',

            password='x',

            role='seller',

        )

        ShopProfile.objects.create(

            seller_id=self.seller.username,

            shop_name=OFFICIAL_SHOP_NAME,

            shop_code='expdemo',

            address='演示地址',

            is_listed=True,

        )

        mark_shop_official(self.seller.username)

        Dish.objects.create(

            seller_id=self.seller.username,

            name='演示矿泉水',

            price=Decimal('2.00'),

            is_active=True,

        )

        profile = MenuProfile.objects.create(seller_id=self.seller.username, name='通用清单')

        populate_profile_with_dishes(profile, self.seller.username)

        from waimai.operating_helpers import get_operating_settings

        settings = get_operating_settings(self.seller.username)

        settings.active_menu_profile = profile

        settings.save(update_fields=['active_menu_profile'])



    def test_experience_products_major_5_includes_step12_screenshot(self):
        """第 5 大步应嵌入第 12 小步固定截图容器"""
        resp = self.client.get(
            '/experience/preview/seller/products/?exp=1&exp_track=seller&exp_major=4&exp_micro=0',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'demo-s5-step12-shot')
        self.assertContains(resp, 'step12-added-dish.png')

    def test_experience_products_major_6_standalone_prepares_dish(self):
        """第 6 大步可从主页单独进入，系统自动准备演示商品"""
        self.assertFalse(
            Dish.objects.filter(seller_id=self.seller.username, name=DEMO_DISH_NAME).exists(),
        )
        resp = self.client.get(
            '/experience/preview/seller/products/?exp=1&exp_track=seller&exp_major=5&exp_micro=0',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            Dish.objects.filter(seller_id=self.seller.username, name=DEMO_DISH_NAME).exists(),
        )
        self.assertContains(resp, 'experience-s6-demo')
        self.assertContains(resp, 'demo-s6-shot-1')
        self.assertContains(resp, 'demo-s6-shot-6')
        self.assertContains(resp, 'step1-summary.png')
        self.assertContains(resp, 'yc-exp-seller-6-screenshots')

    def test_experience_products_major_5_entry_no_edit_panel(self):
        """第 5 大步独立进入时不应自动展开编辑区"""
        dish = Dish.objects.create(
            seller_id=self.seller.username,
            name=DEMO_DISH_NAME,
            price=Decimal('99'),
            is_active=True,
        )
        from waimai.onboarding.demo_cleanup import register_demo_dish
        register_demo_dish(dish.dish_id)
        pick = dish.dish_id.hex[:8]
        resp = self.client.get(
            '/experience/preview/seller/products/?exp=1&exp_track=seller&exp_major=4&exp_micro=0',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, f'id="edit-{pick}"')

    def test_experience_home_ok(self):

        resp = self.client.get('/experience/')

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, '新手体验')

        self.assertContains(resp, 'yc-experience-boot')

        self.assertNotContains(resp, 'id="yc-onboarding-boot"')



    def test_experience_operating_preview_ok(self):

        resp = self.client.get('/experience/preview/seller/operating/')

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, 'operating-intro')



    def test_experience_products_preview_ok(self):

        resp = self.client.get('/experience/preview/seller/products/')

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, 'menu-intro')

        self.assertContains(resp, 'menu-profile-name')

        self.assertContains(resp, '可写演示')

        self.assertContains(resp, 'add-image')
        self.assertContains(resp, 'nav-preview-shop')



    def test_experience_print_qr_preview_ok(self):

        resp = self.client.get(

            '/experience/preview/seller/print-qr/?exp=1&exp_track=seller&exp_major=3&exp_micro=2',

        )

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, 'print-qr-intro')

        self.assertContains(resp, 'print-qr-g18-hint')

        self.assertContains(resp, 'print-qr-btn')



    def test_experience_workbench_preview_ok(self):

        resp = self.client.get('/experience/preview/seller/workbench/')

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, 'workbench-intro')

        self.assertContains(resp, 'workbench-qr-link')

        self.assertContains(resp, 'workbench-alert-volume')

        self.assertContains(resp, '演示员工')

        self.assertContains(resp, 'attendance-log-stream')



    def test_experience_dine_preview_ok(self):

        resp = self.client.get(

            '/experience/preview/seller/dine/?exp=1&exp_track=seller&exp_major=7&exp_micro=0',

        )

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, 'fold-dine-rules')

        self.assertContains(resp, 'dine-rules-content')

        self.assertContains(resp, 'fold-dining-settings')

        self.assertContains(resp, 'data-yc-tour="dine-channel"')

        self.assertContains(resp, 'table-min-max')

        self.assertContains(resp, '可写演示')



    def test_experience_delivery_preview_ok(self):

        from waimai.operating_helpers import get_operating_settings

        settings = get_operating_settings(self.seller.username)

        settings.plugin_fulfillment_enabled = True

        settings.save(update_fields=['plugin_fulfillment_enabled'])

        resp = self.client.get(

            '/experience/preview/seller/delivery/?exp=1&exp_track=seller&exp_major=7&exp_micro=0',

        )

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, 'delivery-intro')

        self.assertContains(resp, 'delivery-multiplier-3-6')

        self.assertContains(resp, 'delivery-multiplier-6-9')

        self.assertContains(resp, 'delivery-discount')

        self.assertContains(resp, 'nav-delivery')



    def test_experience_delivery_redirect_without_plugin(self):

        from waimai.operating_helpers import get_operating_settings

        settings = get_operating_settings(self.seller.username)

        settings.plugin_fulfillment_enabled = False

        settings.save(update_fields=['plugin_fulfillment_enabled'])

        resp = self.client.get('/experience/preview/seller/delivery/')

        self.assertEqual(resp.status_code, 302)

        self.assertIn('/experience/', resp.url)



    def test_experience_payment_preview_ok(self):

        from waimai.operating_helpers import get_operating_settings

        settings = get_operating_settings(self.seller.username)

        settings.plugin_fulfillment_enabled = True

        settings.save(update_fields=['plugin_fulfillment_enabled'])

        resp = self.client.get(

            '/experience/preview/seller/payment/?exp=1&exp_track=seller&exp_major=8&exp_micro=0',

        )

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, 'payment-intro')

        self.assertContains(resp, 'payment-wechat-mch-id')

        self.assertContains(resp, 'payment-notify-url')

        self.assertContains(resp, 'nav-payment')

        self.assertContains(resp, 'rider-cash-box')



    def test_experience_orders_preview_ok(self):

        from decimal import Decimal

        from waimai.models import BuyOrder

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

        resp = self.client.get(

            '/experience/preview/seller/orders/?exp=1&exp_track=seller&exp_major=9&exp_micro=0',

        )

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, 'orders-intro')

        self.assertContains(resp, 'orders-pagination')

        self.assertContains(resp, 'nav-orders')

        self.assertContains(resp, 'fold-boss-notify')

        boot = build_experience_boot_payload()

        detail_url = boot['pages'].get('preview_order_detail', '')

        self.assertIn(str(order.order_id), detail_url)

        resp = self.client.get(

            f'/experience/preview/seller/orders/{order.order_id}/?exp=1&exp_track=seller&exp_major=9&exp_micro=14',

        )

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, 'preview-banner')

        self.assertContains(resp, 'order-detail-hero')

        self.assertContains(resp, 'order-detail-contact')

        self.assertContains(resp, 'order-detail-buyer')

        self.assertContains(resp, 'order-detail-items')

        self.assertContains(resp, 'order-detail-fee-total')

        self.assertContains(resp, 'order-detail-payment')

        self.assertContains(resp, 'order-detail-timeline')



    def test_experience_homepage_preview_ok(self):

        resp = self.client.get(

            '/experience/preview/seller/homepage/?exp=1&exp_track=seller&exp_major=10&exp_micro=0',

        )

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, 'fold-home-settings')

        self.assertContains(resp, 'demo-home-preset-labels')

        self.assertContains(resp, 'experience-home-custom-demo')

        self.assertContains(resp, 'nav-homepage')

        self.assertNotContains(resp, '图片链接')

        resp2 = self.client.get(

            '/experience/preview/seller/homepage-showcase/?exp=1&exp_track=seller&exp_major=10&exp_micro=23',

        )

        self.assertEqual(resp2.status_code, 200)

        self.assertContains(resp2, 'shop-home-header')

        self.assertContains(resp2, 'shop-home-nav-about')

        self.assertContains(resp2, 'shop-home-custom-module')

        self.assertContains(resp2, '野草系统是什么')



    def test_experience_dine_batch_add_tables(self):

        resp = self.client.post(

            '/experience/preview/seller/dine/',

            {

                'add_table': '1',

                'table_min': '1',

                'table_max': '3',

                'exp': '1',

                'exp_track': 'seller',

                'exp_major': '7',

                'exp_micro': '20',

            },

            follow=True,

        )

        self.assertEqual(resp.status_code, 200)

        from waimai.models import ShopTable

        nums = list(

            ShopTable.objects.filter(seller_id=self.seller.username)

            .values_list('table_number', flat=True),

        )

        self.assertIn('1', nums)

        self.assertIn('3', nums)



    def test_experience_table_stickers_preview(self):

        from waimai.models import ShopTable

        from waimai.plugins.dining.table_bulk_helpers import bulk_create_tables

        bulk_create_tables(self.seller.username, 1, 2)

        tables = list(ShopTable.objects.filter(seller_id=self.seller.username))

        ids = ','.join(str(t.table_id) for t in tables)

        resp = self.client.get(

            f'/experience/preview/seller/table-stickers/?tables={ids}&exp=1',

        )

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, 'table-sticker-grid')



    def test_experience_cleanup_removes_demo_tables(self):

        from waimai.models import ShopTable

        from waimai.plugins.dining.table_bulk_helpers import bulk_create_tables

        bulk_create_tables(self.seller.username, 1, 2)

        self.assertEqual(ShopTable.objects.filter(seller_id=self.seller.username).count(), 2)

        result = cleanup_experience_demo_data(self.seller.username)

        self.assertGreaterEqual(result.get('deleted_tables', 0), 2)

        self.assertEqual(ShopTable.objects.filter(seller_id=self.seller.username).count(), 0)



    def test_experience_pick_menu_profile_ajax(self):
        active = get_active_menu_profile(self.seller.username)
        demo = MenuProfile.objects.create(seller_id=self.seller.username, name=DEMO_MENU_PROFILE_NAME)
        resp = self.client.get(
            f'/experience/preview/seller/products/?profile={demo.profile_id}&exp=1&exp_track=seller&exp_major=2&exp_micro=14',
            HTTP_X_EXPERIENCE_MENU_PICK='1',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertIn(DEMO_MENU_PROFILE_NAME, data['menuPanelHtml'])

    def test_experience_create_demo_menu_ajax(self):
        active = get_active_menu_profile(self.seller.username)
        resp = self.client.post(
            '/experience/preview/seller/products/',
            {
                'create_menu_profile': '1',
                'profile_name': DEMO_MENU_PROFILE_NAME,
                'copy_from_profile_id': str(active.profile_id),
                'exp': '1',
                'exp_track': 'seller',
                'exp_major': '2',
                'exp_micro': '12',
                'experience_menu_ajax': '1',
            },
            HTTP_X_EXPERIENCE_MENU_AJAX='1',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertIn('menuPanelHtml', data)
        self.assertIn('演示清单1', data['menuPanelHtml'])

    def test_experience_activate_menu_profile_ajax(self):
        """切换使用：须带 activate_menu_profile，否则后端会拒"""
        active = get_active_menu_profile(self.seller.username)
        demo = MenuProfile.objects.create(seller_id=self.seller.username, name=DEMO_MENU_PROFILE_NAME)
        populate_profile_with_dishes(demo, self.seller.username)
        bad = self.client.post(
            '/experience/preview/seller/products/',
            {
                'profile_id': str(demo.profile_id),
                'exp': '1',
                'exp_track': 'seller',
                'exp_major': '2',
                'exp_micro': '15',
                'experience_menu_ajax': '1',
            },
            HTTP_X_EXPERIENCE_MENU_AJAX='1',
        )
        self.assertEqual(bad.status_code, 200)
        bad_data = bad.json()
        self.assertFalse(bad_data['ok'])
        self.assertTrue(
            any('菜单清单' in m.get('text', '') for m in bad_data.get('messages', [])),
        )
        resp = self.client.post(
            '/experience/preview/seller/products/',
            {
                'activate_menu_profile': '1',
                'profile_id': str(demo.profile_id),
                'exp': '1',
                'exp_track': 'seller',
                'exp_major': '2',
                'exp_micro': '15',
                'experience_menu_ajax': '1',
            },
            HTTP_X_EXPERIENCE_MENU_AJAX='1',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(get_active_menu_profile(self.seller.username).profile_id, demo.profile_id)
        self.assertIn('使用中', data['menuPanelHtml'])

    def test_experience_add_demo_dish_ajax(self):
        resp = self.client.post(
            '/experience/preview/seller/products/',
            {
                'add_dish': '1',
                'name': DEMO_DISH_NAME,
                'price': '99',
                'sort_order': '0',
                'description': '普通描述演示',
                'description_member': '会员描述演示',
                'description_special': '特价描述演示',
                'member_price_enabled': '1',
                'special_price_enabled': '1',
                'list_on_all_menus': '1',
                'experience_demo_image': '1',
                'exp': '1',
                'exp_track': 'seller',
                'exp_major': '4',
                'exp_micro': '10',
                'experience_product_ajax': '1',
            },
            HTTP_X_EXPERIENCE_PRODUCT_AJAX='1',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertIn(DEMO_DISH_NAME, data['productListHtml'])
        dish = Dish.objects.get(seller_id=self.seller.username, name=DEMO_DISH_NAME)
        self.assertEqual(dish.price, Decimal('99'))
        self.assertTrue(dish.member_price_enabled)
        self.assertTrue(dish.special_price_enabled)
        self.assertTrue(dish.product_images.exists())
        self.assertTrue(data['editDishPick'])

    def test_experience_edit_demo_dish_ajax(self):
        dish = Dish.objects.create(
            seller_id=self.seller.username,
            name=DEMO_DISH_NAME,
            price=Decimal('99'),
            is_active=True,
            member_price_enabled=True,
            special_price_enabled=True,
        )
        from waimai.onboarding.demo_cleanup import register_demo_dish
        register_demo_dish(dish.dish_id)
        resp = self.client.post(
            '/experience/preview/seller/products/',
            {
                'edit_dish': '1',
                'dish_id': str(dish.dish_id),
                'name': DEMO_DISH_NAME,
                'price': '99',
                'sort_order': '0',
                'exp': '1',
                'exp_track': 'seller',
                'exp_major': '5',
                'exp_micro': '3',
                'experience_product_ajax': '1',
            },
            HTTP_X_EXPERIENCE_PRODUCT_AJAX='1',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        dish.refresh_from_db()
        self.assertEqual(dish.name, DEMO_DISH_NAME)
        self.assertIn(DEMO_DISH_NAME, data['productListHtml'])

    def test_experience_demo_image_upload_ajax(self):
        dish = Dish.objects.create(
            seller_id=self.seller.username,
            name=DEMO_DISH_NAME,
            price=Decimal('99'),
            is_active=True,
        )
        from waimai.onboarding.demo_cleanup import register_demo_dish
        register_demo_dish(dish.dish_id)
        before = dish.product_images.count()
        resp = self.client.post(
            '/experience/preview/seller/products/',
            {
                'experience_demo_image_upload': '1',
                'dish_id': str(dish.dish_id),
                'exp': '1',
                'exp_track': 'seller',
                'exp_major': '5',
                'exp_micro': '2',
                'experience_product_ajax': '1',
            },
            HTTP_X_EXPERIENCE_PRODUCT_AJAX='1',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        dish.refresh_from_db()
        self.assertGreater(dish.product_images.count(), before)

    def test_experience_edit_rejects_non_demo_dish(self):
        dish = Dish.objects.create(
            seller_id=self.seller.username,
            name='普通商品',
            price=Decimal('1.00'),
            is_active=True,
        )
        resp = self.client.post(
            '/experience/preview/seller/products/',
            {
                'edit_dish': '1',
                'dish_id': str(dish.dish_id),
                'name': '黑客改名',
                'price': '2.00',
                'experience_product_ajax': '1',
            },
            HTTP_X_EXPERIENCE_PRODUCT_AJAX='1',
        )
        data = resp.json()
        self.assertFalse(data['ok'])
        dish.refresh_from_db()
        self.assertEqual(dish.name, '普通商品')

    def test_experience_create_demo_menu(self):

        active = get_active_menu_profile(self.seller.username)

        resp = self.client.post('/experience/preview/seller/products/', {

            'create_menu_profile': '1',

            'profile_name': DEMO_MENU_PROFILE_NAME,

            'copy_from_profile_id': str(active.profile_id),

            'exp': '1',

            'exp_track': 'seller',

            'exp_major': '2',

            'exp_micro': '12',

        })

        self.assertEqual(resp.status_code, 302)

        self.assertTrue(

            MenuProfile.objects.filter(

                seller_id=self.seller.username,

                name=DEMO_MENU_PROFILE_NAME,

            ).exists(),

        )



    def test_experience_cleanup(self):

        MenuProfile.objects.create(seller_id=self.seller.username, name=DEMO_MENU_PROFILE_NAME)

        dish = Dish.objects.create(

            seller_id=self.seller.username,

            name=DEMO_DISH_NAME,

            price=Decimal('3.50'),

            is_active=True,

        )

        from waimai.onboarding.demo_cleanup import register_demo_dish

        register_demo_dish(dish.dish_id)

        dish.name = '演示商品（已改）'

        dish.save(update_fields=['name'])

        resp = self.client.post('/experience/cleanup/')

        self.assertEqual(resp.status_code, 200)

        data = resp.json()

        self.assertTrue(data['ok'])

        self.assertFalse(

            MenuProfile.objects.filter(

                seller_id=self.seller.username,

                name=DEMO_MENU_PROFILE_NAME,

            ).exists(),

        )

        self.assertFalse(

            Dish.objects.filter(seller_id=self.seller.username, dish_id=dish.dish_id).exists(),

        )



    def test_experience_on_server_home(self):

        resp = self.client.get('/')

        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, '体验开店')

        self.assertContains(resp, 'experience-start-btn')

        self.assertContains(resp, 'yc-experience-boot')

        self.assertContains(resp, 'experience-welcome-modal')

        self.assertContains(resp, '欢迎来到野草生态')

        self.assertNotContains(resp, 'block-experience')

        self.assertNotContains(resp, 'id="yc-onboarding-boot"')

        self.assertNotContains(resp, 'onboarding-welcome-modal')

        self.assertNotContains(resp, '新版体验（试运行）')

