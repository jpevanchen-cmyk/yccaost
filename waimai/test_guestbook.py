# 留言板正式功能 · 自动验收

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from waimai.guestbook_code_helpers import generate_public_code, is_valid_public_code_format
from waimai.guestbook_helpers import hash_guest_password, verify_guest_password
from waimai.guestbook_models import GuestbookThread
from waimai.home_page_helpers import BLOCK_CONTACT_US, ensure_server_home_page
from waimai.models import ShopProfile

User = get_user_model()


class GuestbookCodeTests(TestCase):
    def test_generate_unique_code(self):
        code = generate_public_code()
        self.assertTrue(is_valid_public_code_format(code))
        self.assertEqual(code.count('-'), 2)
        self.assertTrue(code.startswith('YC-'))


class GuestbookPostTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)

    def test_post_creates_thread_with_code(self):
        resp = self.client.post(
            '/guestbook/post/',
            {
                'body': '你好，这是一条测试留言',
                'guest_name': '测试访客',
                'guest_email': '',
            },
            HTTP_X_YC_GUESTBOOK='1',
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('ok'))
        self.assertTrue(is_valid_public_code_format(data.get('public_code', '')))
        self.assertEqual(GuestbookThread.objects.count(), 1)

    def test_password_hash_roundtrip(self):
        thread = GuestbookThread.objects.create(
            public_code=generate_public_code(),
            guest_display_name='访客',
            guest_password_hash=hash_guest_password('abc123'),
        )
        self.assertTrue(verify_guest_password(thread, 'abc123'))
        self.assertFalse(verify_guest_password(thread, 'wrong'))


class GuestbookBlockTests(TestCase):
    def setUp(self):
        User.objects.create_user(username='shop1', password='x', role='seller')
        ShopProfile.objects.create(
            seller_id='shop1',
            shop_name='测试店',
            shop_code='testshop1',
            address='测试地址',
            is_listed=True,
        )

    def test_contact_us_block_exists(self):
        page = ensure_server_home_page()
        self.assertTrue(page.blocks.filter(block_type=BLOCK_CONTACT_US).exists())

    def test_homepage_shows_contact_block(self):
        ensure_server_home_page()
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'guestbook-new-form')
        self.assertContains(resp, '输入编号继续沟通')


class GuestbookOpenTests(TestCase):
    def setUp(self):
        User.objects.create_user(username='shop1', password='x', role='seller')
        ShopProfile.objects.create(
            seller_id='shop1',
            shop_name='测试店',
            shop_code='testshop1',
            address='测试地址',
            is_listed=True,
        )
        self.client = Client(enforce_csrf_checks=False)

    def test_open_by_code_get_ok(self):
        code = generate_public_code()
        thread = GuestbookThread.objects.create(
            public_code=code,
            guest_display_name='访客',
            guest_password_hash='',
        )
        from waimai.guestbook_models import GuestbookMessage

        GuestbookMessage.objects.create(
            thread=thread, author_side='guest', author_label='访客', body='测试内容',
        )
        resp = self.client.get(f'/guestbook/t/{code}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, code)
        self.assertContains(resp, '测试内容')

    def test_open_search_redirects(self):
        code = generate_public_code()
        GuestbookThread.objects.create(public_code=code, guest_display_name='访客')
        resp = self.client.post('/guestbook/open/', {'public_code': code})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(code, resp['Location'])


class GuestbookDedupeTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)

    def test_duplicate_submit_returns_same_code(self):
        body = {
            'body': '重复提交测试内容',
            'guest_name': '测试',
            'guest_email': '',
        }
        headers = {'HTTP_X_YC_GUESTBOOK': '1', 'HTTP_ACCEPT': 'application/json'}
        r1 = self.client.post('/guestbook/post/', body, **headers)
        r2 = self.client.post('/guestbook/post/', body, **headers)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        c1 = r1.json()['public_code']
        c2 = r2.json()['public_code']
        self.assertEqual(c1, c2)
        self.assertTrue(r2.json().get('duplicate'))
        self.assertEqual(GuestbookThread.objects.count(), 1)


class GuestbookEmailStatusTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.email = 'guest@test.example'

    def _fill_hourly_limit(self):
        from waimai.email_rate_limit_helpers import KIND_TEST
        from waimai.models import EmailSendLog

        for _ in range(5):
            EmailSendLog.objects.create(recipient=self.email, kind=KIND_TEST)

    def test_rate_limited_not_marked_as_email_failed(self):
        self._fill_hourly_limit()
        resp = self.client.post(
            '/guestbook/post/',
            {
                'body': '防刷上限测试留言',
                'guest_name': '测试',
                'guest_email': self.email,
            },
            HTTP_X_YC_GUESTBOOK='1',
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('ok'))
        self.assertEqual(data.get('result_type'), 'rate_limited')
        self.assertFalse(data.get('email_failed'))
        self.assertTrue(data.get('email_rate_limited'))
        thread = GuestbookThread.objects.get(public_code=data['public_code'])
        self.assertTrue(thread.receipt_email_rate_limited)
        self.assertFalse(thread.receipt_email_failed)

    def test_thread_page_rate_limit_no_email_form(self):
        code = generate_public_code()
        GuestbookThread.objects.create(
            public_code=code,
            guest_display_name='访客',
            guest_email=self.email,
            receipt_email_rate_limited=True,
        )
        resp = self.client.get(f'/guestbook/t/{code}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '邮件通知较频繁')
        self.assertNotContains(resp, 'update_guest_email')

    def test_thread_page_email_failed_shows_update_form(self):
        code = generate_public_code()
        GuestbookThread.objects.create(
            public_code=code,
            guest_display_name='访客',
            guest_email=self.email,
            receipt_email_failed=True,
            guest_actor_key='anon:testactor',
        )
        session = self.client.session
        session['yc_gb_actor_key'] = 'testactor'
        session.save()
        resp = self.client.get(f'/guestbook/t/{code}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '更新联系邮箱')
        self.assertContains(resp, 'name="guest_email"')
