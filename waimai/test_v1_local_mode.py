# V1 本地营业内测：模式开关与隐藏清单

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from waimai.test_shop_helpers import create_logged_in_seller_client, create_test_shop_bundle
from waimai.v1_local_helpers import (
    INSTALL_MODE_STANDARD,
    INSTALL_MODE_V1_LOCAL,
    path_is_v1_blocked,
    seller_section_hidden_in_v1,
    set_db_install_mode,
    should_serve_uploaded_media,
    uploaded_media_urlpatterns,
    v1_local_mode_enabled,
)

class V1LocalHelpersTests(TestCase):
    def test_default_not_v1(self):
        self.assertFalse(v1_local_mode_enabled())
        from waimai.owner_helpers import get_site_settings

        self.assertEqual(get_site_settings().install_mode, INSTALL_MODE_STANDARD)

    @override_settings(YECAO_V1_LOCAL_MODE=True)
    def test_env_enables_v1(self):
        self.assertTrue(v1_local_mode_enabled())

    def test_db_install_mode_enables_v1(self):
        set_db_install_mode(INSTALL_MODE_V1_LOCAL)
        self.assertTrue(v1_local_mode_enabled())
        set_db_install_mode(INSTALL_MODE_STANDARD)
        self.assertFalse(v1_local_mode_enabled())

    def test_blocked_paths(self):
        self.assertTrue(path_is_v1_blocked('/'))
        self.assertTrue(path_is_v1_blocked('/register/'))
        self.assertTrue(path_is_v1_blocked('/shop-register/'))
        self.assertTrue(path_is_v1_blocked('/experience/'))
        self.assertTrue(path_is_v1_blocked('/guestbook/post/'))
        self.assertTrue(path_is_v1_blocked('/s/ABC/home/'))
        self.assertFalse(path_is_v1_blocked('/accounts/login/'))
        self.assertFalse(path_is_v1_blocked('/shop/'))
        self.assertFalse(path_is_v1_blocked('/seller-panel/orders/'))

    @override_settings(YECAO_V1_LOCAL_MODE=True)
    def test_seller_homepage_section_hidden_in_v1(self):
        self.assertTrue(seller_section_hidden_in_v1('homepage'))
        self.assertFalse(seller_section_hidden_in_v1('orders'))

    def test_seller_homepage_section_visible_when_not_v1(self):
        self.assertFalse(seller_section_hidden_in_v1('homepage'))

    @override_settings(DEBUG=False, YECAO_V1_LOCAL_MODE=False)
    def test_media_not_served_by_app_when_cloud_like(self):
        self.assertFalse(should_serve_uploaded_media())
        self.assertEqual(uploaded_media_urlpatterns(), [])

    @override_settings(DEBUG=False, YECAO_V1_LOCAL_MODE=True)
    def test_media_served_by_app_in_v1_without_debug(self):
        self.assertTrue(should_serve_uploaded_media())
        # 关调试也必须挂上路由（不能依赖 django.static，它会返回空）
        self.assertTrue(uploaded_media_urlpatterns())


@override_settings(YECAO_V1_LOCAL_MODE=False)
class V1LocalModeOffHttpTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_register_available_when_not_v1(self):
        response = self.client.get('/register/')
        self.assertEqual(response.status_code, 200)


@override_settings(YECAO_V1_LOCAL_MODE=True)
class V1LocalModeOnHttpTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_register_blocked(self):
        response = self.client.get('/register/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_shop_register_blocked(self):
        response = self.client.get('/shop-register/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_home_blocked(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_experience_blocked(self):
        response = self.client.get('/experience/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_login_still_ok(self):
        response = self.client.get('/accounts/login/')
        self.assertEqual(response.status_code, 200)

    def test_shop_page_still_ok(self):
        response = self.client.get('/shop/')
        self.assertEqual(response.status_code, 200)

    def test_login_hides_register_links(self):
        response = self.client.get('/accounts/login/')
        self.assertNotContains(response, '买家注册')
        self.assertNotContains(response, '店铺开通')


@override_settings(YECAO_V1_LOCAL_MODE=True)
class V1LocalSellerHomepageHiddenTests(TestCase):
    def setUp(self):
        self.bundle = create_test_shop_bundle(username='v1_hide_hp_seller')
        self.client = create_logged_in_seller_client(self.bundle)

    def test_seller_nav_excludes_homepage(self):
        from waimai.plugin_runtime.registry import collect_seller_nav_items

        sections = {item.section for item in collect_seller_nav_items(self.bundle.seller.username)}
        self.assertNotIn('homepage', sections)
        self.assertIn('orders', sections)

    def test_seller_homepage_section_redirects(self):
        url = reverse('seller_panel_section', kwargs={'section': 'homepage'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/seller-panel/orders/', response['Location'])

    def test_seller_orders_hides_homepage_tab(self):
        url = reverse('seller_panel_section', kwargs={'section': 'orders'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'nav-homepage')
        self.assertNotContains(response, '🏠 店铺主页')

    def test_seller_panel_no_top_back_button(self):
        url = reverse('seller_panel_section', kwargs={'section': 'orders'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'class="page-back-btn"')
        self.assertNotContains(response, '返回主页')
        self.assertNotContains(response, '返回订单管理')
