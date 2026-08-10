# 员工考勤：老板补改时间点与流水分页

from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from waimai.models import StaffAttendanceLog, User
from waimai.time_helpers import to_local, now_local_wall
from waimai.staff_account_helpers import (
    STAFF_WORK_BREAK,
    STAFF_WORK_ON_DUTY,
    STAFF_WORK_OFF_DUTY,
    build_workbench_attendance_context,
    datetime_local_input_value,
    parse_local_datetime_input,
)


class AttendanceManagerFixTest(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='att_seller',
            password='pass12345',
            role='seller',
        )
        self.staff = User.objects.create_user(
            username='att_seller::demo_staff',
            password='pass12345',
            role='waiter',
            employer_seller_id='att_seller',
            staff_account_type='employee',
            staff_job_title='演示员工',
            staff_work_status=STAFF_WORK_OFF_DUTY,
        )
        self.client = Client()
        self.client.login(username='att_seller', password='pass12345')

    def test_manager_off_duty_with_custom_time(self):
        when = now_local_wall() - timedelta(hours=2)
        resp = self.client.post(
            reverse('seller_panel_section', kwargs={'section': 'workbench'}),
            {
                'manager_set_staff_status': '1',
                'attendance_username': self.staff.username,
                'attendance_status': STAFF_WORK_OFF_DUTY,
                'attendance_at': datetime_local_input_value(when),
                'attendance_note': '补下班',
            },
        )
        self.assertEqual(resp.status_code, 302)
        log = StaffAttendanceLog.objects.filter(user=self.staff).order_by('-changed_at').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.action, STAFF_WORK_OFF_DUTY)
        self.assertEqual(
            to_local(log.changed_at).replace(second=0, microsecond=0),
            to_local(when).replace(second=0, microsecond=0),
        )

    def test_manager_break_creates_period_logs(self):
        start = now_local_wall() - timedelta(hours=3)
        end = now_local_wall() - timedelta(hours=2)
        resp = self.client.post(
            reverse('seller_panel_section', kwargs={'section': 'workbench'}),
            {
                'manager_set_staff_status': '1',
                'attendance_username': self.staff.username,
                'attendance_status': STAFF_WORK_BREAK,
                'break_start': datetime_local_input_value(start),
                'break_end': datetime_local_input_value(end),
            },
        )
        self.assertEqual(resp.status_code, 302)
        logs = list(StaffAttendanceLog.objects.filter(user=self.staff).order_by('changed_at'))
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].action, STAFF_WORK_BREAK)
        self.assertEqual(logs[1].action, STAFF_WORK_ON_DUTY)

    def test_workbench_attendance_defaults_today(self):
        old = now_local_wall() - timedelta(days=3)
        StaffAttendanceLog.objects.create(
            user=self.staff,
            seller_id='att_seller',
            username_snapshot=self.staff.username,
            display_name_snapshot='演示员工',
            role_snapshot='waiter',
            action=STAFF_WORK_ON_DUTY,
            source='self',
            changed_at=old,
        )
        request = self.client.get('/seller-panel/workbench/').wsgi_request
        ctx = build_workbench_attendance_context(
            request,
            'att_seller',
            '90',
            [self.staff],
            default_today=True,
        )
        self.assertEqual(ctx['attendance_logs_page'].paginator.count, 0)

        today_log_time = now_local_wall()
        StaffAttendanceLog.objects.create(
            user=self.staff,
            seller_id='att_seller',
            username_snapshot=self.staff.username,
            display_name_snapshot='演示员工',
            role_snapshot='waiter',
            action=STAFF_WORK_ON_DUTY,
            source='self',
            changed_at=today_log_time,
        )
        ctx = build_workbench_attendance_context(
            request,
            'att_seller',
            '90',
            [self.staff],
            default_today=True,
        )
        self.assertEqual(ctx['attendance_logs_page'].paginator.count, 1)

    def test_parse_local_datetime_input(self):
        from django.conf import settings

        parsed = parse_local_datetime_input('2026-07-29T15:30')
        self.assertIsNotNone(parsed)
        # USE_TZ=False 时写库须无时区本地墙钟；True 时才带时区
        if settings.USE_TZ:
            self.assertTrue(timezone.is_aware(parsed))
        else:
            self.assertTrue(timezone.is_naive(parsed))
            self.assertEqual(parsed.hour, 15)
            self.assertEqual(parsed.minute, 30)

    def test_attendance_full_page_ok(self):
        resp = self.client.get(reverse('seller_panel_attendance_logs'))
        self.assertEqual(resp.status_code, 200)
