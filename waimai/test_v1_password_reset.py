# V1 第 11 项：本机忘记密码重置

from django.contrib.auth import get_user_model
from django.test import TestCase

from launcher.tray_password_helpers import (
    clear_tray_password,
    password_is_configured,
    set_tray_password,
    verify_tray_password,
)
from waimai.models import LoginGuardState
from waimai.operation_lock_helpers import (
    operation_lock_configured,
    set_operation_lock_pin,
)
from waimai.owner_helpers import get_site_settings
from waimai.staff_account_helpers import create_owner_workbench_staff
from waimai.v1_password_reset_helpers import (
    CONFIRM_PHRASE,
    clear_operation_lock_pin_local,
    clear_tray_startup_exit_password,
    confirm_phrase_ok,
    reset_owner_login_password,
)

User = get_user_model()


class V1PasswordResetTests(TestCase):
    def setUp(self):
        clear_tray_password()
        self.owner = User.objects.create_user(
            username='boss_reset',
            password='OldPass123',
            role='seller',
        )
        self.owner.is_server_owner = True
        self.owner.save(update_fields=['is_server_owner'])
        create_owner_workbench_staff(self.owner, 'OldPass123')

    def tearDown(self):
        clear_tray_password()

    def test_confirm_phrase(self):
        self.assertTrue(confirm_phrase_ok(CONFIRM_PHRASE))
        self.assertFalse(confirm_phrase_ok('确认'))

    def test_reset_owner_and_staff_password(self):
        ok, msg = reset_owner_login_password('boss_reset', 'NewPass456')
        self.assertTrue(ok, msg)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password('NewPass456'))
        staff = User.objects.filter(username='boss_reset::boss_reset').first()
        self.assertIsNotNone(staff)
        self.assertTrue(staff.check_password('NewPass456'))

    def test_reset_clears_login_guard(self):
        LoginGuardState.objects.create(
            scope='ecosystem',
            guard_key='127.0.0.1|boss_reset',
            fail_count=3,
        )
        ok, msg = reset_owner_login_password('boss_reset', 'NewPass789')
        self.assertTrue(ok, msg)
        self.assertFalse(
            LoginGuardState.objects.filter(guard_key__icontains='boss_reset').exists()
        )

    def test_clear_tray_password(self):
        set_tray_password('TraySecret1', startup_enabled=True, exit_enabled=True)
        self.assertTrue(password_is_configured())
        ok, msg = clear_tray_startup_exit_password()
        self.assertTrue(ok, msg)
        self.assertFalse(password_is_configured())
        self.assertTrue(verify_tray_password('anything'))

    def test_clear_operation_lock(self):
        site = get_site_settings()
        set_operation_lock_pin(site, '1234')
        site.operation_lock_enabled = True
        site.save()
        self.assertTrue(operation_lock_configured(get_site_settings()))
        ok, msg = clear_operation_lock_pin_local()
        self.assertTrue(ok, msg)
        self.assertFalse(operation_lock_configured(get_site_settings()))

    def test_command_requires_confirm(self):
        from django.core.management import call_command
        from io import StringIO

        err = StringIO()
        with self.assertRaises(Exception):
            call_command(
                'yecao_reset_local_password',
                clear_tray=True,
                stderr=err,
            )
