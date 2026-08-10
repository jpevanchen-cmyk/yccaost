# V1 第 8 项：登录防试密码 + 审计

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from waimai.login_guard_helpers import (
    LOGIN_GUARD_MAX_FAILURES,
    SCOPE_ECOSYSTEM,
    SCOPE_SHOP_WORK,
    build_login_guard_key,
    check_login_allowed,
    record_login_failure,
)
from waimai.models import LoginGuardState, OperationAuditLog
from waimai.staff_account_helpers import create_owner_workbench_staff
from waimai.test_shop_helpers import create_test_shop_bundle

User = get_user_model()


class LoginGuardHelperTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_fifth_failure_triggers_lock(self):
        request = self.factory.post('/accounts/login/')
        username = 'bad_user'
        for i in range(LOGIN_GUARD_MAX_FAILURES - 1):
            locked, msg = record_login_failure(
                request, SCOPE_ECOSYSTEM, username=username,
            )
            self.assertFalse(locked)
            self.assertIn(f'已连续错 {i + 1} 次', msg)
        locked, msg = record_login_failure(
            request, SCOPE_ECOSYSTEM, username=username,
        )
        self.assertTrue(locked)
        self.assertIn('分钟', msg)
        self.assertIn('已暂锁', msg)
        allowed, _ = check_login_allowed(
            request, SCOPE_ECOSYSTEM, username=username,
        )
        self.assertFalse(allowed)

    def test_guard_key_includes_shop_for_workbench(self):
        request = self.factory.post('/s/test/work/')
        key = build_login_guard_key(
            request,
            SCOPE_SHOP_WORK,
            username='waiter1',
            seller_id='shop_a',
        )
        self.assertIn('shop_a', key)


class EcosystemLoginGuardTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='eco_guard_buyer',
            password='right_pass',
            role='buyer',
        )

    def _fail_login(self, password='wrong'):
        return self.client.post(
            reverse('login'),
            {'username': self.user.username, 'password': password},
        )

    def test_lock_after_repeated_wrong_password(self):
        for i in range(LOGIN_GUARD_MAX_FAILURES):
            resp = self._fail_login()
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, f'已连续错 {i + 1} 次')
        blocked = self._fail_login()
        self.assertContains(blocked, '分钟')
        self.assertGreaterEqual(
            OperationAuditLog.objects.filter(action_code='login_locked').count(),
            1,
        )
        self.assertGreaterEqual(
            OperationAuditLog.objects.filter(action_code='login_failed').count(),
            LOGIN_GUARD_MAX_FAILURES,
        )

    def test_success_clears_guard(self):
        factory = RequestFactory()
        request = factory.post('/accounts/login/')
        for _ in range(3):
            record_login_failure(
                request, SCOPE_ECOSYSTEM, username=self.user.username,
            )
        ok = self.client.post(
            reverse('login'),
            {'username': self.user.username, 'password': 'right_pass'},
        )
        self.assertEqual(ok.status_code, 302)
        client_request = factory.post('/accounts/login/')
        key = build_login_guard_key(
            client_request, SCOPE_ECOSYSTEM, username=self.user.username,
        )
        self.assertFalse(
            LoginGuardState.objects.filter(
                scope=SCOPE_ECOSYSTEM, guard_key=key,
            ).exists(),
        )


class ShopWorkLoginGuardTests(TestCase):
    def setUp(self):
        self.bundle = create_test_shop_bundle(username='lg_shop_seller')
        self.seller_id = self.bundle.seller.username
        self.shop_code = self.bundle.shop.shop_code
        create_owner_workbench_staff(self.bundle.seller, 'badge_pass')
        self.client = Client()
        self.url = reverse('shop_work', kwargs={'shop_code': self.shop_code})

    def _fail_login(self):
        return self.client.post(
            self.url,
            {'username': self.seller_id, 'password': 'wrong'},
        )

    def test_workbench_locks_after_failures(self):
        for _ in range(LOGIN_GUARD_MAX_FAILURES):
            resp = self._fail_login()
            self.assertEqual(resp.status_code, 200)
        blocked = self._fail_login()
        self.assertEqual(blocked.status_code, 200)
        self.assertTrue(
            OperationAuditLog.objects.filter(
                action_code='login_locked',
                seller_id=self.seller_id,
            ).exists(),
        )
        allowed, lock_msg = check_login_allowed(
            blocked.wsgi_request,
            SCOPE_SHOP_WORK,
            username=self.seller_id,
            seller_id=self.seller_id,
        )
        self.assertFalse(allowed)
        self.assertIn('分钟', lock_msg)

    def test_workbench_success_after_failures(self):
        for _ in range(2):
            self._fail_login()
        ok = self.client.post(
            self.url,
            {'username': self.seller_id, 'password': 'badge_pass'},
        )
        self.assertEqual(ok.status_code, 302)
