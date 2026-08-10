# 店铺工作台：无全站顶栏

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from waimai.shop_work_auth import establish_shop_work_session
from waimai.staff_account_helpers import create_owner_workbench_staff, staff_internal_username
from waimai.test_shop_helpers import DEFAULT_TEST_PASSWORD, create_test_shop_bundle

User = get_user_model()


class WorkbenchChromeTests(TestCase):
    def setUp(self):
        self.bundle = create_test_shop_bundle(username='wb_chrome_seller')
        self.shop_code = self.bundle.shop.shop_code
        create_owner_workbench_staff(self.bundle.seller, DEFAULT_TEST_PASSWORD)
        self.staff = User.objects.get(
            username=staff_internal_username(self.bundle.seller.username, self.bundle.seller.username),
        )
        self.client = Client()

    def test_login_page_hides_site_top(self):
        url = reverse('shop_work', kwargs={'shop_code': self.shop_code})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'shop-work-site')
        self.assertNotContains(resp, 'id="site-nav"')
        self.assertNotContains(resp, '管理店铺')
        self.assertContains(resp, '工牌名字和密码')

    def test_hub_page_hides_site_top_when_logged_in(self):
        session = self.client.session
        establish_shop_work_session(
            type('R', (), {'session': session})(),
            self.staff,
            seller_id=self.bundle.seller.username,
            shop_code=self.shop_code,
        )
        session.save()
        url = reverse('shop_work', kwargs={'shop_code': self.shop_code})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'shop-work-site')
        self.assertNotContains(resp, 'id="site-nav"')
        self.assertNotContains(resp, '返回店铺管理')

    def test_seller_panel_still_has_site_top(self):
        seller_client = Client()
        seller_client.login(username=self.bundle.seller.username, password=DEFAULT_TEST_PASSWORD)
        orders = seller_client.get(reverse('seller_panel_section', kwargs={'section': 'orders'}))
        self.assertEqual(orders.status_code, 200)
        self.assertContains(orders, 'id="site-nav"')
