# 登录暂锁邮件

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from waimai.login_guard_helpers import (
    LOGIN_GUARD_MAX_FAILURES,
    SCOPE_ECOSYSTEM,
    handle_failed_login_attempt,
)
from waimai.login_lock_notify_helpers import (
    notify_login_locked_email,
    resolve_locked_account_email,
)

User = get_user_model()


class LoginLockNotifyTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='lock_mail_user',
            password='pass1234',
            email='locked@example.com',
            role='buyer',
        )

    def test_resolve_email_by_username(self):
        email = resolve_locked_account_email(
            SCOPE_ECOSYSTEM, username=self.user.username,
        )
        self.assertEqual(email, 'locked@example.com')

    def test_no_email_for_unknown_user(self):
        self.assertEqual(
            resolve_locked_account_email(SCOPE_ECOSYSTEM, username='nobody'),
            '',
        )

    @patch('waimai.login_lock_notify_helpers.send_yecao_mail', return_value=True)
    @patch('waimai.login_lock_notify_helpers.is_email_ready', return_value=True)
    def test_notify_on_lock(self, _ready, send_mail):
        ok = notify_login_locked_email(
            scope=SCOPE_ECOSYSTEM,
            username=self.user.username,
            portal_label='野草生态',
        )
        self.assertTrue(ok)
        send_mail.assert_called_once()
        self.assertIn('盗号风险', send_mail.call_args.kwargs['message'])

    @patch('waimai.login_lock_notify_helpers.notify_login_locked_email')
    def test_handle_failure_triggers_notify_at_lock(self, notify_mock):
        request = self.factory.post('/accounts/login/')
        for _ in range(LOGIN_GUARD_MAX_FAILURES):
            handle_failed_login_attempt(
                request,
                SCOPE_ECOSYSTEM,
                username=self.user.username,
            )
        notify_mock.assert_called_once()
