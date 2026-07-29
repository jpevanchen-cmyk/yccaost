# 新版新手体验（独立模块 v2）测试



from decimal import Decimal



from django.test import TestCase



from waimai.experience_helpers import mark_shop_official

from waimai.menu_helpers import get_active_menu_profile, populate_profile_with_dishes

from waimai.models import Dish, MenuProfile, ShopProfile, User

from waimai.onboarding.boot import build_experience_boot_payload

from waimai.onboarding.demo_cleanup import DEMO_DISH_NAME, DEMO_MENU_PROFILE_NAME, cleanup_experience_demo_data

from waimai.onboarding_helpers import OFFICIAL_SHOP_NAME





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

        settings.save(update_fields=['active_menu_profile'])



    def test_boot_has_seven_majors(self):

        boot = build_experience_boot_payload()

        self.assertTrue(boot['enabled'])

        self.assertEqual(boot['version'], 2)

        seller = boot['tracks']['seller']

        self.assertEqual(len(seller), 7)

        self.assertEqual(seller[0]['id'], 'seller-1')

        self.assertEqual(seller[1]['id'], 'seller-2')

        self.assertEqual(seller[2]['id'], 'seller-3')

        self.assertEqual(seller[3]['id'], 'seller-4')

        self.assertEqual(seller[4]['id'], 'seller-5')

        self.assertEqual(seller[5]['id'], 'seller-6')

        self.assertEqual(seller[6]['id'], 'seller-7')

        self.assertTrue(seller[2].get('cleanupOnComplete'))

        self.assertTrue(seller[5].get('cleanupOnComplete'))



    def test_boot_has_menu_tour_meta(self):

        boot = build_experience_boot_payload()

        self.assertEqual(boot['urlFlag'], 'exp')

        self.assertIn('/experience/preview/seller/products/', boot['pages']['preview_products'])

        self.assertTrue(boot['demoCopyProfileId'])

        self.assertIn('/experience/cleanup/', boot['cleanupUrl'])

        self.assertIn('preview_products', boot['writablePages'])

        self.assertIn('/experience/preview/seller/print-qr/', boot['pages']['preview_print_qr'])

        self.assertIn('/experience/preview/seller/workbench/', boot['pages']['preview_workbench_manage'])

        workbench_major = boot['tracks']['seller'][6]
        self.assertEqual(workbench_major['id'], 'seller-7')
        # 合并 3 个小步后共 37 步；有履约插件时 +2
        self.assertIn(len(workbench_major['microSteps']), (37, 39))
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
        self.assertEqual(
            register_major['microSteps'][1]['selector'],
            '[data-yc-tour="experience-start-btn"]',
        )

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

        self.assertContains(resp, '7 大步')

        self.assertNotContains(resp, 'block-experience')

        self.assertNotContains(resp, 'id="yc-onboarding-boot"')

        self.assertNotContains(resp, 'onboarding-welcome-modal')

        self.assertNotContains(resp, '新版体验（试运行）')

